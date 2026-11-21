"""Independent reference implementation of the frozen entry-signal formulas.

This module deliberately imports no research_agent.core or shared indicator code.
It reproduces the documented formula semantics using separate calculations and
returns plain dictionaries so primary Signal objects are not required.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Iterable


_STRATEGIES = (
    "Donchian20", "EMA20x50", "RSI14Trend50", "MACD12x26", "Keltner20x2ATR",
)


def _field(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name)
    except AttributeError as exc:
        raise ValueError(f"Missing required field: {name}") from exc


def _bars(candles: Iterable[Any]) -> list[Any]:
    data = list(candles)
    if not data:
        raise ValueError("Signal reference requires candles")
    previous = None
    timezone_mode = None
    for i, bar in enumerate(data):
        stamp = _field(bar, "timestamp")
        if not isinstance(stamp, datetime):
            raise ValueError(f"Invalid timestamp at row {i}")
        aware = stamp.tzinfo is not None and stamp.utcoffset() is not None
        if timezone_mode is None:
            timezone_mode = aware
        elif aware != timezone_mode:
            raise ValueError(f"Mixed timestamp timezone modes at row {i}")
        if previous is not None and stamp <= previous:
            raise ValueError(f"Non-increasing timestamp at row {i}")
        previous = stamp
        op, hi, lo, close, volume = (
            _field(bar, key) for key in ("open", "high", "low", "close", "volume")
        )
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in (op, hi, lo, close, volume)):
            raise ValueError(f"Invalid numeric OHLCV at row {i}")
        if min(op, hi, lo, close) <= 0 or volume < 0 or hi < max(op, lo, close) or lo > min(op, hi, close):
            raise ValueError(f"Invalid OHLCV geometry at row {i}")
    return data


def _exp_average(values: list[float], length: int) -> list[float]:
    # Match the frozen formula's first-observation seed, independently coded.
    smoothing = 2.0 / (length + 1.0)
    output: list[float] = []
    level = values[0]
    for observation in values:
        level = smoothing * observation + (1.0 - smoothing) * level
        output.append(level)
    return output


def _relative_strength(prices: list[float], length: int) -> list[float | None]:
    output: list[float | None] = [None] * len(prices)
    if len(prices) <= length:
        return output
    changes = [prices[k] - prices[k - 1] for k in range(1, len(prices))]
    positive = [max(change, 0.0) for change in changes]
    negative = [max(-change, 0.0) for change in changes]
    up = sum(positive[:length]) / length
    down = sum(negative[:length]) / length
    for bar_index in range(length, len(prices)):
        if bar_index != length:
            slot = bar_index - 1
            up = (up * (length - 1) + positive[slot]) / length
            down = (down * (length - 1) + negative[slot]) / length
        if up == 0 and down == 0:
            output[bar_index] = 50.0
        elif down == 0:
            output[bar_index] = 100.0
        else:
            output[bar_index] = 100.0 - 100.0 / (1.0 + up / down)
    return output


def _true_range_average(data: list[Any], length: int) -> list[float | None]:
    ranges: list[float] = []
    for i, bar in enumerate(data):
        high, low = bar.high, bar.low
        if i == 0:
            ranges.append(high - low)
        else:
            prior_close = data[i - 1].close
            ranges.append(max(high - low, abs(high - prior_close), abs(low - prior_close)))
    output: list[float | None] = [None] * len(data)
    if len(data) < length:
        return output
    value = sum(ranges[:length]) / length
    output[length - 1] = value
    for i in range(length, len(data)):
        value = (value * (length - 1) + ranges[i]) / length
        output[i] = value
    return output


def reference_generate_signals(candles: Iterable[Any]) -> list[dict[str, Any]]:
    """Recalculate all five frozen strategies without calling primary indicators."""
    data = _bars(candles)
    closes = [bar.close for bar in data]
    fast12 = _exp_average(closes, 12)
    medium20 = _exp_average(closes, 20)
    slow26 = _exp_average(closes, 26)
    slow50 = _exp_average(closes, 50)
    macd_line = [a - b for a, b in zip(fast12, slow26)]
    macd_average = _exp_average(macd_line, 9)
    rsi = _relative_strength(closes, 14)
    atr = _true_range_average(data, 14)

    events: list[dict[str, Any]] = []
    for i in range(55, len(data) - 1):
        previous_window = data[i - 20:i]
        ceiling = max(bar.high for bar in previous_window)
        floor = min(bar.low for bar in previous_window)

        def emit(direction: int, strategy: str) -> None:
            events.append({"index": i, "direction": direction, "strategy": strategy})

        if closes[i] > ceiling:
            emit(1, "Donchian20")
        elif closes[i] < floor:
            emit(-1, "Donchian20")

        if medium20[i] > slow50[i] and medium20[i - 1] <= slow50[i - 1]:
            emit(1, "EMA20x50")
        elif medium20[i] < slow50[i] and medium20[i - 1] >= slow50[i - 1]:
            emit(-1, "EMA20x50")

        if rsi[i] is not None and rsi[i - 1] is not None:
            if medium20[i] > slow50[i] and rsi[i] > 50 and rsi[i - 1] <= 50:
                emit(1, "RSI14Trend50")
            elif medium20[i] < slow50[i] and rsi[i] < 50 and rsi[i - 1] >= 50:
                emit(-1, "RSI14Trend50")

        if macd_line[i] > macd_average[i] and macd_line[i - 1] <= macd_average[i - 1]:
            emit(1, "MACD12x26")
        elif macd_line[i] < macd_average[i] and macd_line[i - 1] >= macd_average[i - 1]:
            emit(-1, "MACD12x26")

        if atr[i] is not None and atr[i - 1] is not None:
            upper_now = medium20[i] + 2.0 * atr[i]
            upper_before = medium20[i - 1] + 2.0 * atr[i - 1]
            lower_now = medium20[i] - 2.0 * atr[i]
            lower_before = medium20[i - 1] - 2.0 * atr[i - 1]
            if closes[i] > upper_now and closes[i - 1] <= upper_before:
                emit(1, "Keltner20x2ATR")
            elif closes[i] < lower_now and closes[i - 1] >= lower_before:
                emit(-1, "Keltner20x2ATR")
    return events


def audit_signal_generation(candles: Iterable[Any], primary_signals: Iterable[Any]) -> dict[str, Any]:
    """Compare ordered primary events with independently regenerated events."""
    expected = reference_generate_signals(candles)
    actual = []
    for pos, signal in enumerate(primary_signals):
        event = {
            "index": _field(signal, "index"),
            "direction": _field(signal, "direction"),
            "strategy": _field(signal, "strategy"),
        }
        if (not isinstance(event["index"], int) or isinstance(event["index"], bool)
                or event["direction"] not in (-1, 1)
                or event["strategy"] not in _STRATEGIES):
            raise ValueError(f"Invalid primary signal at position {pos}")
        actual.append(event)
    mismatches: list[dict[str, Any]] = []
    if len(actual) != len(expected):
        mismatches.append({"field": "event_count", "actual": len(actual), "expected": len(expected)})
    for position, (left, right) in enumerate(zip(actual, expected)):
        for field in ("index", "direction", "strategy"):
            if left[field] != right[field]:
                mismatches.append({
                    "event_index": position, "field": field,
                    "actual": left[field], "expected": right[field],
                })
    return {
        "status": "REFERENCE_SIGNAL_MATCH" if not mismatches else "REFERENCE_SIGNAL_MISMATCH",
        "primary_signal_count": len(actual),
        "reference_signal_count": len(expected),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "strategies_checked": list(_STRATEGIES),
        "scope": "Independent formula replay; validates event parity on supplied candles, not raw-data provenance or profitability.",
    }
