from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class ApiError(RuntimeError):
    pass


def get_json(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "reversal-bot/1.0", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise ApiError(f"GET failed: {url}: {exc}") from exc


def num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_klines(symbol: str, interval: str, limit: int) -> list[dict[str, float]]:
    sources = [
        ("bybit", "https://api.bybit.com/v5/market/kline", {"category": "linear", "symbol": symbol, "interval": "D" if interval == "1d" else "240", "limit": limit}),
        ("bingx", "https://open-api.bingx.com/openApi/swap/v3/quote/klines", {"symbol": symbol.removesuffix("USDT") + "-USDT", "interval": interval, "limit": limit}),
        ("binance", "https://fapi.binance.com/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit}),
    ]
    for _, url, params in sources:
        try:
            payload = get_json(url, params)
            rows = payload.get("result", {}).get("list", []) if isinstance(payload, dict) and "result" in payload else payload.get("data", payload) if isinstance(payload, dict) else payload
            parsed = []
            for row in rows or []:
                if isinstance(row, dict):
                    item = {"timestamp": num(row.get("time") or row.get("openTime")), "open": num(row.get("open")), "high": num(row.get("high")), "low": num(row.get("low")), "close": num(row.get("close")), "volume": num(row.get("volume"))}
                elif len(row) >= 6:
                    item = {"timestamp": num(row[0]), "open": num(row[1]), "high": num(row[2]), "low": num(row[3]), "close": num(row[4]), "volume": num(row[5])}
                else:
                    continue
                if all(item[key] is not None for key in ("open", "high", "low", "close", "volume")):
                    parsed.append(item)
            if len(parsed) >= min(30, limit // 2):
                return sorted(parsed, key=lambda row: row["timestamp"] or 0)
        except ApiError:
            continue
    return []


def fetch_market_data(symbol: str) -> dict[str, float | None]:
    sources = [
        ("bybit", "https://api.bybit.com/v5/market/tickers", {"category": "linear", "symbol": symbol}),
        ("bingx", "https://open-api.bingx.com/openApi/swap/v2/quote/ticker", {"symbol": symbol.removesuffix("USDT") + "-USDT"}),
        ("binance", "https://fapi.binance.com/fapi/v1/ticker/24hr", {"symbol": symbol}),
    ]
    for name, url, params in sources:
        try:
            payload = get_json(url, params)
            row = payload.get("result", {}).get("list", [{}])[0] if name == "bybit" else payload.get("data", payload)
            if isinstance(row, list):
                row = row[0] if row else {}
            if name == "binance":
                contract_volume = num(row.get("quoteVolume"))
                funding = None
            else:
                contract_volume = num(row.get("turnover24h") or row.get("quoteVolume"))
                funding = num(row.get("fundingRate"))
            oi = fetch_current_oi_usd(symbol)
            spot_volume = fetch_spot_volume(symbol)
            return {"contract_volume": contract_volume, "spot_volume": spot_volume, "funding": funding, "oi": oi}
        except ApiError:
            continue
    return {"contract_volume": None, "spot_volume": None, "funding": None, "oi": None}


def fetch_current_oi_usd(symbol: str) -> float | None:
    try:
        payload = get_json("https://api.bybit.com/v5/market/open-interest", {"category": "linear", "symbol": symbol, "intervalTime": "5min", "limit": 1})
        row = payload.get("result", {}).get("list", [{}])[0]
        oi_coins = num(row.get("openInterest"))
        ticker = get_json("https://api.bybit.com/v5/market/tickers", {"category": "linear", "symbol": symbol})
        price = num(ticker.get("result", {}).get("list", [{}])[0].get("lastPrice"))
        if oi_coins and price:
            return oi_coins * price
    except ApiError:
        pass
    try:
        payload = get_json("https://open-api.bingx.com/openApi/swap/v2/quote/openInterest", {"symbol": symbol.removesuffix("USDT") + "-USDT"})
        row = payload.get("data", {})
        amount = num(row.get("openInterest") or row.get("amount") or row.get("volume")) if isinstance(row, dict) else None
        ticker = get_json("https://open-api.bingx.com/openApi/swap/v2/quote/ticker", {"symbol": symbol.removesuffix("USDT") + "-USDT"})
        ticker_row = ticker.get("data", {})
        price = num(ticker_row.get("lastPrice")) if isinstance(ticker_row, dict) else None
        if amount and price:
            return amount * price
    except ApiError:
        pass
    return None


def fetch_spot_volume(symbol: str) -> float | None:
    try:
        payload = get_json("https://api.bybit.com/v5/market/tickers", {"category": "spot", "symbol": symbol})
        row = payload.get("result", {}).get("list", [{}])[0]
        value = num(row.get("turnover24h") or row.get("quoteVolume"))
        if value is not None:
            return value
    except ApiError:
        pass
    try:
        payload = get_json("https://api.binance.com/api/v3/ticker/24hr", {"symbol": symbol})
        return num(payload.get("quoteVolume"))
    except ApiError:
        return None


def fetch_cmc(cache_path: str, ttl: int, api_key: str, listing_limit: int = 1000) -> dict[str, dict[str, Any]]:
    cache = Path(cache_path)
    if cache.exists() and time.time() - cache.stat().st_mtime < ttl:
        return json.loads(cache.read_text(encoding="utf-8"))
    headers = {"X-CMC_PRO_API_KEY": api_key} if api_key else {}
    urls = [
        ("https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest", headers),
        ("https://pro-api.coinmarketcap.com/public-api/v3/cryptocurrency/listings/latest", {}),
    ]
    for url, request_headers in urls:
        try:
            payload = get_json(url, {"start": 1, "limit": listing_limit, "convert": "USD"}, request_headers)
            rows = payload.get("data", [])
            result = {}
            for row in rows:
                quote = row.get("quote", {})
                if isinstance(quote, list):
                    quote = next((item for item in quote if item.get("name") == "USD" or item.get("symbol") == "USD"), {})
                usd = quote.get("USD", quote) if isinstance(quote, dict) else {}
                result[str(row.get("symbol", "")).upper()] = {"rank": row.get("cmc_rank"), "market_cap": num(usd.get("market_cap")), "volume": num(usd.get("volume_24h"))}
            if result:
                cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                return result
        except ApiError:
            continue
    return json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
