from __future__ import annotations

from dataclasses import dataclass
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


def _within(a: float, b: float, tolerance: float) -> bool:
    return max(a, b) > 0 and abs(a - b) / max(a, b) <= tolerance


def _signal(
    name: str,
    bullish: bool,
    structure: int,
    confirmed: bool,
    near_trigger: bool,
    volume: float,
    timeframe: str,
    reasons: list[str],
    trigger_text: str,
) -> PatternSignal:
    """Use one shared scoring model so non-U patterns have equal opportunity."""
    trigger_score = 15 if confirmed else 7 if near_trigger else 0
    volume_score = 10 if volume >= 1.4 else 5 if volume >= 1.0 else 0
    daily_score = 5 if timeframe == "1d" else 0
    score = min(95, 25 + structure + trigger_score + volume_score + daily_score)
    completion = min(98, 40 + structure + trigger_score + volume_score)
    direction = ("LONG" if confirmed else "偏多觀察") if bullish else ("SHORT" if confirmed else "偏空觀察")
    confidence = "高" if score >= 80 else "中" if score >= 70 else "低"
    missing = [] if confirmed else [trigger_text]
    if volume < 1.2:
        missing.append("突破或跌破時成交量放大")
    return PatternSignal(name, score, completion, direction, confidence, reasons, missing)


def _u_bottom(values: list[float], volume: float, timeframe: str) -> PatternSignal | None:
    recent = values[-min(len(values), 120):]
    trough = min(range(len(recent)), key=lambda i: recent[i])
    if trough < 20 or len(recent) - trough < 15:
        return None
    left, right = recent[:trough], recent[trough + 1 :]
    if not left or not right:
        return None
    low = recent[trough]
    left_rim = max(left[-min(45, len(left)) : -8])
    right_rim = max(right)
    neckline = (left_rim + right_rim) / 2
    prior_decline = (left_rim - low) / left_rim if left_rim else 0
    low_zone = [i for i, value in enumerate(recent) if value <= low * 1.10]
    broad_bottom = len(low_zone) >= 8 and low_zone[-1] - low_zone[0] >= 10
    balanced_rims = _within(left_rim, right_rim, 0.30)
    right_rising = recent[-1] >= low * 1.12
    near = recent[-1] >= neckline * 0.95
    confirmed = recent[-1] >= neckline * 0.995
    not_overextended = recent[-1] <= neckline * 1.25
    if prior_decline < 0.15 or not broad_bottom or not balanced_rims or not right_rising or not not_overextended:
        return None
    return _signal(
        "U 型底",
        True,
        30,
        confirmed,
        near,
        volume,
        timeframe,
        ["前段下跌後形成寬底圓弧", "低檔停留時間足夠", "左右杯緣接近且右側墊高"],
        "有效突破頸線",
    )


def _w_bottom(values: list[float], lows: list[int], volume: float, timeframe: str) -> PatternSignal | None:
    if len(lows) < 2:
        return None
    a, b = lows[-2], lows[-1]
    if not 8 <= b - a <= 90 or b < len(values) - 55:
        return None
    first, second = values[a], values[b]
    neckline = max(values[a : b + 1])
    near = values[-1] >= neckline * 0.95
    confirmed = values[-1] >= neckline * 0.995
    if not _within(first, second, 0.10) or neckline < min(first, second) * 1.10 or second < first * 0.90:
        return None
    return _signal("W 底", True, 30, confirmed, near, volume, timeframe, ["雙低點高度接近", "中間反彈形成頸線", "第二低點守住"], "有效突破頸線")


def _m_top(values: list[float], highs: list[int], volume: float, timeframe: str) -> PatternSignal | None:
    if len(highs) < 2:
        return None
    a, b = highs[-2], highs[-1]
    if not 8 <= b - a <= 90 or b < len(values) - 55:
        return None
    first, second = values[a], values[b]
    neckline = min(values[a : b + 1])
    near = values[-1] <= neckline * 1.05
    confirmed = values[-1] <= neckline * 1.005
    if not _within(first, second, 0.10) or neckline > max(first, second) * 0.90 or second > first * 1.10:
        return None
    return _signal("M 頂", False, 30, confirmed, near, volume, timeframe, ["雙高點高度接近", "中間回落形成頸線", "第二高點未有效創高"], "有效跌破頸線")


def _head_shoulders_bottom(values: list[float], lows: list[int], volume: float, timeframe: str) -> PatternSignal | None:
    if len(lows) < 3:
        return None
    left, head, right = lows[-3:]
    if right < len(values) - 65:
        return None
    lv, hv, rv = values[left], values[head], values[right]
    neckline = min(max(values[left : head + 1]), max(values[head : right + 1]))
    near = values[-1] >= neckline * 0.95
    confirmed = values[-1] >= neckline * 0.995
    if not (hv <= lv * 0.92 and hv <= rv * 0.92 and _within(lv, rv, 0.18)):
        return None
    return _signal("頭肩底", True, 30, confirmed, near, volume, timeframe, ["頭部低於左右肩", "左右肩高度接近", "頸線清楚"], "有效突破頸線")


def _head_shoulders_top(values: list[float], highs: list[int], volume: float, timeframe: str) -> PatternSignal | None:
    if len(highs) < 3:
        return None
    left, head, right = highs[-3:]
    if right < len(values) - 65:
        return None
    lv, hv, rv = values[left], values[head], values[right]
    neckline = max(min(values[left : head + 1]), min(values[head : right + 1]))
    near = values[-1] <= neckline * 1.05
    confirmed = values[-1] <= neckline * 1.005
    if not (hv >= lv * 1.08 and hv >= rv * 1.08 and _within(lv, rv, 0.18)):
        return None
    return _signal("頭肩頂", False, 30, confirmed, near, volume, timeframe, ["頭部高於左右肩", "左右肩高度接近", "頸線清楚"], "有效跌破頸線")


def _inverted_u_top(values: list[float], volume: float, timeframe: str) -> PatternSignal | None:
    recent = values[-min(len(values), 120):]
    peak = max(range(len(recent)), key=lambda i: recent[i])
    if peak < 12 or len(recent) - peak < 12:
        return None
    left, right = recent[:peak], recent[peak + 1 :]
    high = recent[peak]
    support = min(right)
    prior_rise = (high - min(left)) / min(left) if min(left) else 0
    rounded = _within(max(left), max(right), 0.14)
    near = recent[-1] <= support * 1.05
    confirmed = recent[-1] <= support * 1.005
    if prior_rise < 0.15 or not rounded or recent[-1] > high * 0.94:
        return None
    return _signal("倒 U 型頂", False, 30, confirmed, near, volume, timeframe, ["前段上漲後高位圓弧鈍化", "右側出現轉弱結構"], "有效跌破圓弧下緣支撐")


def _cup_handle(values: list[float], volume: float, timeframe: str) -> PatternSignal | None:
    recent = values[-min(len(values), 160):]
    if len(recent) < 45:
        return None
    search_end = max(22, int(len(recent) * 0.55))
    left = max(range(8, search_end), key=lambda i: recent[i])
    trough_end = max(left + 10, len(recent) - 16)
    if trough_end <= left + 4:
        return None
    trough = min(range(left + 5, trough_end), key=lambda i: recent[i])
    right_start = trough + 8
    right_end = len(recent) - 3
    if right_start >= right_end:
        return None
    right = max(range(right_start, right_end), key=lambda i: recent[i])
    handle = recent[right:]
    if not 4 <= len(handle) <= 32:
        return None
    lip = max(recent[left], recent[right])
    depth = (lip - recent[trough]) / lip if lip else 0
    handle_depth = (recent[right] - min(handle)) / (recent[right] - recent[trough]) if recent[right] > recent[trough] else 1
    near = recent[-1] >= lip * 0.95
    confirmed = recent[-1] >= lip * 0.995
    if not (0.08 <= depth <= 0.55 and _within(recent[left], recent[right], 0.12) and handle_depth <= 0.35):
        return None
    return _signal("杯柄底", True, 30, confirmed, near, volume, timeframe, ["圓弧杯底", "右側回到接近杯口", "柄部回落受控"], "有效突破杯口")


def signal_for(rows: list[dict[str, float]], timeframe: str) -> PatternSignal | None:
    values = closes(rows)
    if len(values) < 40:
        return None
    lows, highs = swing_points(values, 3 if timeframe == "1d" else 4)
    if not lows or not highs:
        return None
    volume = volume_ratio(rows)

    # U 型底是唯一優先型態；其餘型態使用完全相同的選擇權重。
    u_bottom = _u_bottom(values, volume, timeframe)
    if u_bottom:
        return u_bottom

    candidates = [
        _w_bottom(values, lows, volume, timeframe),
        _m_top(values, highs, volume, timeframe),
        _head_shoulders_bottom(values, lows, volume, timeframe),
        _head_shoulders_top(values, highs, volume, timeframe),
        _inverted_u_top(values, volume, timeframe),
        _cup_handle(values, volume, timeframe),
    ]
    valid = [candidate for candidate in candidates if candidate]
    return max(valid, key=lambda signal: signal.score) if valid else None
