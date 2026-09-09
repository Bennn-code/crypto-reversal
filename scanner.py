from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time
from urllib.error import HTTPError
import urllib.parse
import urllib.request
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
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.status != 200:
                    raise RuntimeError(f"Telegram returned {response.status}")
                return
        except HTTPError as exc:
            if exc.code != 429 or attempt == 3:
                raise
            retry_after = 15
            try:
                error = json.loads(exc.read().decode("utf-8"))
                retry_after = int(error.get("parameters", {}).get("retry_after", retry_after))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                pass
            time.sleep(retry_after + 1)


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
    market_cap = meta.get("market_cap")
    volume = meta.get("volume")
    if symbol in EXCLUDED_SYMBOLS:
        return False
    if not isinstance(market_cap, (int, float)) or not settings.min_market_cap_usd <= market_cap <= settings.max_market_cap_usd:
        return False
    return isinstance(volume, (int, float)) and volume >= settings.min_cmc_volume_usd


def apply_h4_confirmation(daily_signal: PatternSignal, h4_signal: PatternSignal | None) -> PatternSignal:
    """Use 4H as confirmation only; keep the daily pattern as the alert label."""
    if not h4_signal:
        return daily_signal

    daily_bullish = daily_signal.direction in {"LONG", "偏多觀察"}
    h4_bullish = h4_signal.direction in {"LONG", "偏多觀察"}
    if daily_bullish == h4_bullish:
        score = min(95, daily_signal.score + (6 if h4_signal.direction in {"LONG", "SHORT"} else 3))
        completion = min(98, daily_signal.completion + 5)
        return PatternSignal(
            daily_signal.name,
            score,
            completion,
            daily_signal.direction,
            "高" if score >= 80 else "中" if score >= 70 else "低",
            [*daily_signal.reasons, f"4H 同向確認：{h4_signal.name}"],
            daily_signal.missing,
        )

    score = max(0, daily_signal.score - 8)
    return PatternSignal(
        daily_signal.name,
        score,
        daily_signal.completion,
        daily_signal.direction,
        "中" if score >= 70 else "低",
        daily_signal.reasons,
        [*daily_signal.missing, f"4H 出現反向結構：{h4_signal.name}"],
    )


def scan(settings) -> list[dict]:
    cmc = fetch_cmc(
        "cmc_cache.json",
        settings.cmc_cache_ttl,
        settings.cmc_api_key,
        settings.cmc_listing_limit,
    )
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
    selected_symbols = symbols if settings.max_symbols <= 0 else symbols[: settings.max_symbols]
    daily_candidates: list[tuple[str, list[dict[str, float]], PatternSignal]] = []

    # Two-stage scan: daily structure first, then expensive 4H/OI enrichment.
    with ThreadPoolExecutor(max_workers=max(1, settings.scan_workers)) as executor:
        futures = {
            executor.submit(fetch_klines, symbol, "1d", 240): symbol
            for symbol in selected_symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                daily = future.result()
            except Exception:
                continue
            d_signal = signal_for(daily, "1d") if daily else None
            if d_signal and d_signal.score >= 55:
                daily_candidates.append((symbol, daily, d_signal))

    qualified: list[tuple[str, list[dict[str, float]], PatternSignal]] = []
    with ThreadPoolExecutor(max_workers=max(1, settings.scan_workers)) as executor:
        futures = {
            executor.submit(fetch_klines, symbol, "4h", 360): (symbol, daily, d_signal)
            for symbol, daily, d_signal in daily_candidates
        }
        for future in as_completed(futures):
            symbol, daily, d_signal = futures[future]
            try:
                h4 = future.result()
            except Exception:
                h4 = []
            h_signal = signal_for(h4, "4h") if h4 else None
            signal = apply_h4_confirmation(d_signal, h_signal) if d_signal else h_signal
            if not signal or signal.score < 60:
                continue
            qualified.append((symbol, daily, signal))

    results = []
    with ThreadPoolExecutor(max_workers=max(1, settings.scan_workers)) as executor:
        futures = {
            executor.submit(fetch_market_data, symbol): (symbol, daily, signal)
            for symbol, daily, signal in qualified
        }
        for future in as_completed(futures):
            symbol, daily, signal = futures[future]
            try:
                market = future.result()
            except Exception:
                market = {"contract_volume": None, "spot_volume": None, "funding": None, "oi": None}
            meta = cmc.get(symbol.removesuffix("USDT"), {})
            spot_volume = market.get("spot_volume")
            contract_volume = market.get("contract_volume")
            candidate = {"symbol": symbol, "signal": signal, "market": market, "meta": meta, "spot_volume": spot_volume, "contract_volume": contract_volume, "volume_ratio": volume_ratio(daily)}
            results.append(candidate)
    results.sort(key=lambda item: item["signal"].score, reverse=True)
    return results if settings.scan_limit <= 0 else results[:settings.scan_limit]


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


def render_summary(
    items: list[dict],
    sent_count: int,
    high_sent_count: int,
    early_sent_count: int,
    cooldown_count: int,
    below_threshold_count: int,
    high_limit_count: int,
    early_limit_count: int,
) -> str:
    lines = [
        "🔄 <b>反轉型態摘要（12 小時）</b>",
        "",
        f"本次掃描候選：{len(items)}",
        f"新訊號已推送：{sent_count}",
        f"HIGH：{high_sent_count}｜EARLY：{early_sent_count}",
        f"Cooldown 暫不重推：{cooldown_count}",
        f"分數未達推送門檻：{below_threshold_count}",
    ]
    if high_limit_count:
        lines.append(f"本輪另有 {high_limit_count} 個 HIGH 因 5 則上限未逐則推送。")
    if early_limit_count:
        lines.append(f"另有 {early_limit_count} 個 EARLY 因每日 5 則上限未逐則推送。")
    if sent_count == 0:
        lines.extend(["", "本次沒有可推送的新型態。", "日線與 4H 掃描已完成。"])
        return "\n".join(lines)

    lines.extend(["", "<b>最接近的型態：</b>"])
    for index, item in enumerate(items[:3], start=1):
        signal: PatternSignal = item["signal"]
        lines.append(
            f"{index}. <b>{item['symbol']}</b>｜{signal.name}｜{signal.score}/100｜{signal.direction}｜完成度 {signal.completion}%"
        )
    lines.append("\n⚠️ 型態掃描僅供觀察，不是直接進場建議。")
    return "\n".join(lines)


def main(summary: bool = False) -> None:
    settings = get_settings()
    items = scan(settings)
    sent_count = 0
    high_sent_count = 0
    early_sent_count = 0
    cooldown_count = 0
    below_threshold_count = 0
    high_limit_count = 0
    early_limit_count = 0
    store = Store(settings.sqlite_path)
    remaining_early = max(0, settings.daily_alert_limit - store.alerts_sent_today(70, 79))
    for item in items:
        signal = item["signal"]
        if signal.score < settings.min_alert_score:
            below_threshold_count += 1
        elif not store.can_alert(item["symbol"], signal.name, signal.direction, settings.cooldown_hours):
            cooldown_count += 1
        elif signal.score >= 80 and high_sent_count >= settings.high_alert_limit_per_scan:
            high_limit_count += 1
            continue
        elif signal.score < 80 and early_sent_count >= remaining_early:
            early_limit_count += 1
            continue
        else:
            send_telegram(settings, render(item))
            store.record_alert(item["symbol"], signal.name, signal.direction, signal.score)
            sent_count += 1
            if signal.score >= 80:
                high_sent_count += 1
            else:
                early_sent_count += 1
            time.sleep(settings.telegram_message_interval_seconds)
    if summary:
        send_telegram(
            settings,
            render_summary(
                items,
                sent_count,
                high_sent_count,
                early_sent_count,
                cooldown_count,
                below_threshold_count,
                high_limit_count,
                early_limit_count,
            ),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan crypto reversal patterns")
    parser.add_argument("--summary", action="store_true", help="send the 12-hour heartbeat summary after scanning")
    args = parser.parse_args()
    main(summary=args.summary)
