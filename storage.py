from __future__ import annotations

import sqlite3
import time


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS alerts (symbol TEXT, pattern TEXT, direction TEXT, created_at INTEGER, PRIMARY KEY(symbol, pattern, direction))")
            db.execute("CREATE TABLE IF NOT EXISTS snapshots (symbol TEXT, timeframe TEXT, ts INTEGER, oi REAL, PRIMARY KEY(symbol, timeframe, ts))")

    def can_alert(self, symbol: str, pattern: str, direction: str, hours: int) -> bool:
        cutoff = int(time.time()) - hours * 3600
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT created_at FROM alerts WHERE symbol=? AND pattern=? AND direction=?", (symbol, pattern, direction)).fetchone()
        return not row or row[0] < cutoff

    def record_alert(self, symbol: str, pattern: str, direction: str) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO alerts VALUES (?, ?, ?, ?)", (symbol, pattern, direction, int(time.time())))

    def save_oi(self, symbol: str, timeframe: str, value: float | None) -> None:
        if value is None:
            return
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?)", (symbol, timeframe, int(time.time()), value))

