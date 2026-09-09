from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from clients import fetch_cmc, fetch_klines, fetch_market_data
from config import get_settings
from patterns import PatternSignal, signal_for, volume_ratio
from storage import Store

EXCLUDED_SYMBOLS = {
    "BTC", "ETH", "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDD",
    "PYUSD", "FRAX", "LUSD", "USDP", "GUSD", "USDS", "USD0", "USN",
}


def send_telegram(settings, text: str) -> None:
    if settings.dry_run:
        print(text)
        return
    if not settings.telegram_token or not settings.chat_id:
        raise RuntimeError("Telegram settings are missing")
    payload = {"chat_id": settings.chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if settings.thread_id is not None:
        payload["message_thread_id"] = settings.thread_id
    data = urllib.parse.urlencode(payload).encode("utf-8")
    url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"
    request = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"Telegram returned {response.status}")


def fmt_money(value: float | None) -> str:
    if value is None:
        return "N/A"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:.0f}"


def is_smallcap_candidate(symbol: str, meta: dict, settings) -> bool:
    rank = meta.get("rank")
    market_cap = meta.get("market_cap")
    volume = meta.get("volume")
    if symbol in EXCLUDED_SYMBOLS:
        return False
    if not isinstance(rank, int) or not settings.min_cmc_rank <= rank <= settings.max_cmc_rank:
        return False
    if not isinstance(market_cap, (int, float)) or not settings.min_market_cap_usd <= market_cap <= settings.max_market_cap_usd:
        return False
    return isinstance(volume, (int, float)) and volume >= settings.min_cmc_volume_usd


def scan(settings) -> list[dict]:
    cmc = fetch_cmc("cmc_cache.json", settings.cmc_cache_ttl, settings.cmc_api_key)
    symbols = sorted(
        (
            symbol + "USDT"
            for symbol, meta in cmc.items()
            if is_smallcap_candidate(symbol, meta, settings)
        ),
        key=lambda item: cmc.get(item.removesuffix("USDT"), {}).get("volume") or 0,
        reverse=True,
    )
    store = Store(settings.sqlite_path)
    results = []
    # Two-stage scan: daily structure first, then expensive 4H/OI enrichment.
    for symbol in symbols[: settings.max_symbols]:
        daily = fetch_klines(symbol, "1d", 240)
        if not daily:
            continue
        d_signal = signal_for(daily, "1d")
        if not d_signal or d_signal.score < 55:
            continue
        h4 = fetch_klines(symbol, "4h", 360)
        h_signal = signal_for(h4, "4h") if h4 else None
        signal = d_signal or h_signal
        if not signal or signal.score < 60:
            continue
        if h_signal and h_signal.direction in {"LONG", "SHORT"} and d_signal and d_signal.direction == "待觀察":
            signal = PatternSignal(signal.name, max(0, signal.score - 5), signal.completion, "待觀察", signal.confidence, signal.reasons, signal.missing)
        market = fetch_market_data(symbol)
        meta = cmc.get(symbol.removesuffix("USDT"), {})
        spot_volume = market.get("spot_volume")
        contract_volume = market.get("contract_volume")
        direction = signal.direction
        candidate = {"symbol": symbol, "signal": signal, "market": market, "meta": meta, "spot_volume": spot_volume, "contract_volume": contract_volume, "volume_ratio": volume_ratio(daily)}
        results.append(candidate)
    results.sort(key=lambda item: item["signal"].score, reverse=True)
    return results[:settings.scan_limit]


def render(item: dict) -> str:
    signal: PatternSignal = item["signal"]
    meta = item["meta"]
    market = item["market"]
    contract = item["contract_volume"]
    spot = item["spot_volume"]
    ratio = contract / spot if contract and spot else None
    checks = "\n".join(f"• {reason}" for reason in signal.reasons)
    missing = "\n".join(f"• {reason}" for reason in signal.missing) or "• 主要條件已完成"
    return f"🔄 <b>反轉機會｜{('HIGH' if signal.score >= 80 else 'EARLY' if signal.score >= 70 else 'WATCH')}</b>\n\n<b>{item['symbol']}</b>｜{signal.name}\n分數：<b>{signal.score}/100</b>｜完成度：{signal.completion}%\n方向：<b>{signal.direction}</b>｜信心：{signal.confidence}\n\n📊 <b>結構判斷</b>\n{checks}\n\n⏳ <b>尚缺條件</b>\n{missing}\n\n📈 <b>24H 量能</b>\n合約：{fmt_money(contract)}\n現貨：{fmt_money(spot)}\n合約/現貨：{f'{ratio:.2f}' if ratio else 'N/A'}\n\n📌 <b>市場資料</b>\nCMC 排名：#{meta.get('rank') or 'N/A'}\n市值：{fmt_money(meta.get('market_cap'))}\n目前 OI：{fmt_money(market.get('oi'))}\n\n⚠️ 型態掃描訊號，並非自動交易建議。"


def render_summary(items: list[dict], sent_count: int, cooldown_count: int) -> str:
    lines = [
        "🔄 <b>反轉型態摘要（12 小時）</b>",
        "",
        f"本次掃描候選：{len(items)}",
        f"新訊號已推送：{sent_count}",
        f"Cooldown 暫不重推：{cooldown_count}",
    ]
    if not items:
        lines.extend(["", "本次沒有掃描到符合條件的反轉型態。", "日線與 4H 掃描已完成。"])
        return "\n".join(lines)

    lines.extend(["", "<b>最接近的型態：</b>"])
    for index, item in enumerate(items[:3], start=1):
        signal: PatternSignal = item["signal"]
        lines.append(
            f"{index}. <b>{item['symbol']}</b>｜{signal.name}｜{signal.score}/100｜{signal.direction}｜完成度 {signal.completion}%"
        )
    lines.append("\n⚠️ 型態掃描僅供觀察，不是直接進場建議。")
    return "\n".join(lines)


def main() -> None:
    settings = get_settings()
    items = scan(settings)
    sent_count = 0
    cooldown_count = 0
    store = Store(settings.sqlite_path)
    for item in items:
        signal = item["signal"]
        if store.can_alert(item["symbol"], signal.name, signal.direction, settings.cooldown_hours):
            send_telegram(settings, render(item))
            store.record_alert(item["symbol"], signal.name, signal.direction)
            sent_count += 1
        else:
            cooldown_count += 1
    # A heartbeat summary is mandatory, even when all candidates are cooling down.
    send_telegram(settings, render_summary(items, sent_count, cooldown_count))


if __name__ == "__main__":
    main()
