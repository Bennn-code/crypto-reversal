from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS alerts (symbol TEXT, pattern TEXT, direction TEXT, created_at INTEGER, score INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(symbol, pattern, direction))")
            columns = {row[1] for row in db.execute("PRAGMA table_info(alerts)")}
            if "score" not in columns:
                db.execute("ALTER TABLE alerts ADD COLUMN score INTEGER NOT NULL DEFAULT 0")
            db.execute("CREATE TABLE IF NOT EXISTS snapshots (symbol TEXT, timeframe TEXT, ts INTEGER, oi REAL, PRIMARY KEY(symbol, timeframe, ts))")

    def can_alert(self, symbol: str, pattern: str, direction: str, hours: int) -> bool:
        cutoff = int(time.time()) - hours * 3600
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT created_at FROM alerts WHERE symbol=? AND pattern=? AND direction=?", (symbol, pattern, direction)).fetchone()
        return not row or row[0] < cutoff

    def record_alert(self, symbol: str, pattern: str, direction: str, score: int) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT OR REPLACE INTO alerts (symbol, pattern, direction, created_at, score) VALUES (?, ?, ?, ?, ?)",
                (symbol, pattern, direction, int(time.time()), score),
            )

    def alerts_sent_today(self, minimum_score: int = 0, maximum_score: int = 100) -> int:
        taipei = timezone(timedelta(hours=8), name="Asia/Taipei")
        now = datetime.now(taipei)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT COUNT(*) FROM alerts WHERE created_at >= ? AND score BETWEEN ? AND ?",
                (int(start.timestamp()), minimum_score, maximum_score),
            ).fetchone()
        return int(row[0] if row else 0)

    def save_oi(self, symbol: str, timeframe: str, value: float | None) -> None:
        if value is None:
            return
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?)", (symbol, timeframe, int(time.time()), value))
