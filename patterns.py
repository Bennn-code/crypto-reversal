from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PatternSignal:
    name: str
    score: int
    completion: int
    direction: str
    confidence: str
    reasons: list[str]
    missing: list[str]


def closes(rows: list[dict[str, float]]) -> list[float]:
    return [float(row["close"]) for row in rows if row.get("close")]


def volume_ratio(rows: list[dict[str, float]], window: int = 20) -> float:
    if len(rows) < window + 2:
        return 0.0
    avg = sum(float(row["volume"]) for row in rows[-window-1:-1]) / window
    return float(rows[-1]["volume"]) / avg if avg else 0.0


def swing_points(values: list[float], radius: int = 3) -> tuple[list[int], list[int]]:
    lows, highs = [], []
    for i in range(radius, len(values) - radius):
        left, right = values[i-radius:i], values[i+1:i+radius+1]
        if values[i] <= min(left) and values[i] <= min(right):
            lows.append(i)
        if values[i] >= max(left) and values[i] >= max(right):
            highs.append(i)
    return lows, highs


def signal_for(rows: list[dict[str, float]], timeframe: str) -> PatternSignal | None:
    values = closes(rows)
    if len(values) < 40:
        return None
    lows, highs = swing_points(values, 3 if timeframe == "1d" else 4)
    if not lows or not highs:
        return None
    recent = values[-min(len(values), 120):]
    low_idx = lows[-8:]
    high_idx = highs[-8:]
    last = values[-1]
    low = min(recent)
    high = max(recent)
    if high <= low:
        return None
    rel = (last - low) / (high - low)
    vol = volume_ratio(rows)
    candidates: list[PatternSignal] = []

    # U bottom: rounded recovery from a persistent low, with a separate neckline high.
    trough = min(range(len(recent)), key=lambda i: recent[i])
    left = recent[:trough]
    right = recent[trough+1:]
    if trough >= 8 and len(right) >= 8 and left and right:
        left_low, right_low = min(left), min(right)
        balanced = abs(left_low - right_low) / max(left_low, right_low) <= 0.16
        right_rising = right[-1] > right_low * 1.08
        neckline = max(recent[max(0, trough-20):trough] or [0])
        breakout = last >= neckline * 0.99 and neckline > low * 1.12
        if balanced and right_rising and neckline > low * 1.1:
            score = 32 + (10 if right_rising else 0) + (12 if breakout else 0) + (8 if vol >= 1.4 else 0)
            candidates.append(PatternSignal("U 型底", min(score + (8 if timeframe == "1d" else 0), 100), min(98, 60 + score // 2), "LONG" if breakout and vol >= 1.2 else "偏多觀察", "高" if breakout and vol >= 1.2 else "中", ["底部圓弧結構", "右側逐步墊高"] + (["已接近或突破頸線"] if breakout else []), [] if breakout else ["日線或 4H 有效突破", "突破時成交量放大"]))

    # W bottom: two nearby troughs with a rebound peak between them.
    if len(low_idx) >= 2:
        a, b = low_idx[-2], low_idx[-1]
        if b - a >= 5:
            va, vb = values[a], values[b]
            between = max(values[a:b+1])
            close_lows = abs(va - vb) / max(va, vb) <= 0.12
            breakout = last >= between * 0.99
            if close_lows and between >= min(va, vb) * 1.08:
                score = 34 + (15 if breakout else 0) + (8 if vol >= 1.4 else 0)
                candidates.append(PatternSignal("W 底", min(score + (8 if timeframe == "1d" else 0), 100), min(96, 58 + score // 2), "LONG" if breakout and vol >= 1.2 else "偏多觀察", "高" if breakout else "中", ["雙底結構", "中間反彈頸線"], [] if breakout else ["突破頸線", "4H 放量確認"]))

    # Head-and-shoulders patterns use the last three meaningful extrema.
    if len(low_idx) >= 3:
        x, y, z = low_idx[-3:]
        vx, vy, vz = values[x], values[y], values[z]
        if vy < vx * 0.92 and vy < vz * 0.92 and abs(vx - vz) / max(vx, vz) <= 0.18:
            neckline = min(max(values[x:y+1]), max(values[y:z+1]))
            breakout = last >= neckline * 0.99
            score = 38 + (15 if breakout else 0) + (8 if vol >= 1.4 else 0)
            candidates.append(PatternSignal("頭肩底", min(score + (8 if timeframe == "1d" else 0), 100), min(96, 60 + score // 2), "LONG" if breakout else "偏多觀察", "高" if breakout else "中", ["頭部低於左右肩", "頸線清楚"], [] if breakout else ["突破頸線", "成交量確認"]))
    if len(high_idx) >= 3:
        x, y, z = high_idx[-3:]
        vx, vy, vz = values[x], values[y], values[z]
        if vy > vx * 1.08 and vy > vz * 1.08 and abs(vx - vz) / max(vx, vz) <= 0.18:
            neckline = max(min(values[x:y+1]), min(values[y:z+1]))
            breakdown = last <= neckline * 1.01
            score = 38 + (15 if breakdown else 0) + (8 if vol >= 1.4 else 0)
            candidates.append(PatternSignal("頭肩頂", min(score + (8 if timeframe == "1d" else 0), 100), min(96, 60 + score // 2), "SHORT" if breakdown else "偏空觀察", "高" if breakdown else "中", ["頭部高於左右肩", "頸線清楚"], [] if breakdown else ["跌破頸線", "成交量確認"]))

    # Inverted U is a rounded top / risk signal.
    if len(recent) >= 20 and recent[-1] < max(recent) * 0.94 and rel > 0.65:
        score = 36 + (12 if vol >= 1.4 else 0)
        candidates.append(PatternSignal("倒 U 型頂", min(score + (8 if timeframe == "1d" else 0), 100), min(90, 55 + score // 2), "SHORT" if recent[-1] < recent[-8] else "偏空觀察", "中", ["高位圓弧轉弱"], ["跌破關鍵支撐"]))

    if not candidates:
        return None
    return max(candidates, key=lambda signal: signal.score)

