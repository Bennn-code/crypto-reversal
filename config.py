from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env(path: str = ".env") -> None:
    file_path = Path(path)
    if not file_path.exists():
        return
    for raw in file_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    chat_id: str
    thread_id: int | None
    cmc_api_key: str
    cmc_cache_ttl: int
    dry_run: bool
    sqlite_path: str
    scan_limit: int
    max_symbols: int
    scan_workers: int
    cooldown_hours: int
    telegram_message_interval_seconds: float
    min_alert_score: int
    daily_alert_limit: int
    min_market_cap_usd: float
    max_market_cap_usd: float
    min_cmc_volume_usd: float
    cmc_listing_limit: int


def get_settings() -> Settings:
    load_env()
    thread = os.getenv("TELEGRAM_THREAD_ID", "").strip()
    return Settings(
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        thread_id=int(thread) if thread else None,
        cmc_api_key=os.getenv("CMC_API_KEY", "").strip(),
        cmc_cache_ttl=int(os.getenv("CMC_CACHE_TTL_SECONDS", "7200")),
        dry_run=env_bool("DRY_RUN", True),
        sqlite_path=os.getenv("SQLITE_PATH", "reversal_alerts.sqlite"),
        scan_limit=int(os.getenv("SCAN_LIMIT", "0")),
        max_symbols=int(os.getenv("MAX_SYMBOLS", "0")),
        scan_workers=int(os.getenv("SCAN_WORKERS", "6")),
        cooldown_hours=int(os.getenv("COOLDOWN_HOURS", "24")),
        telegram_message_interval_seconds=float(os.getenv("TELEGRAM_MESSAGE_INTERVAL_SECONDS", "3.2")),
        min_alert_score=int(os.getenv("MIN_ALERT_SCORE", "70")),
        daily_alert_limit=int(os.getenv("DAILY_ALERT_LIMIT", "5")),
        min_market_cap_usd=float(os.getenv("MIN_MARKET_CAP_USD", "20000000")),
        max_market_cap_usd=float(os.getenv("MAX_MARKET_CAP_USD", "3000000000")),
        min_cmc_volume_usd=float(os.getenv("MIN_CMC_VOLUME_USD", "1000000")),
        cmc_listing_limit=int(os.getenv("CMC_LISTING_LIMIT", "1000")),
    )
