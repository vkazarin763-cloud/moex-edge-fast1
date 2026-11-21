"""Independent reference replay for auditing the production research simulator.

This module intentionally imports no code from research_agent.core or validation.
It consumes their public data objects by attribute only and returns plain dictionaries.
It is a test/audit oracle, not a replacement execution engine.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Iterable


_TRADE_FIELDS = (
    "strategy", "direction", "signal_time", "entry_time", "exit_time",
    "entry_price", "exit_price", "net_return", "status", "exit_reason",
)


def _read(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name)
    except AttributeError as exc:
        raise ValueError(f"Missing required field: {name}") from exc


def _validated_rows(candles: Iterable[Any]) -> list[Any]:
    rows = list(candles)
    if not rows:
        raise ValueError("Reference replay requires candles")
    previous = None
    aware = None
    for i, bar in enumerate(rows):
        ts = _read(bar, "timestamp")
        if not isinstance(ts, datetime):
            raise ValueError(f"Invalid timestamp at row {i}")
        is_aware = ts.tzinfo is not None and ts.utcoffset() is not None
        if aware is None:
            aware = is_aware
        elif aware != is_aware:
            raise ValueError(f"Mixed timestamp timezone modes at row {i}")
        if previous is not None and ts <= previous:
            raise ValueError(f"Non-increasing timestamps at row {i}")
        previous = ts
        o, h, low, c, volume = (
            _read(bar, field) for field in ("open", "high", "low", "close", "volume")
        )
        if not all(math.isfinite(x) for x in (o, h, low, c, volume)):
            raise ValueError(f"Non-finite OHLCV at row {i}")
        if min(o, h, low, c) <= 0 or volume < 0:
            raise ValueError(f"Invalid price or volume at row {i}")
        if h < max(o, c, low) or low > min(o, c, h):
            raise ValueError(f"Invalid OHLC geometry at row {i}")
    return rows


def _execution_parameters(config: Any) -> tuple[float, float, float | None, float | None, int | None]:
    fee = _read(config, "fee_per_side")
    slip = _read(config, "slippage_per_side")
    stop = _read(config, "stop_pct")
    target = _read(config, "target_pct")
    max_bars = _read(config, "max_bars")
    for name, value in (("fee_per_side", fee), ("slippage_per_side", slip)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value < 1:
            raise ValueError(f"Invalid {name}")
    for name, value in (("stop_pct", stop), ("target_pct", target)):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 < value < 1
        ):
            raise ValueError(f"Invalid {name}")
    if max_bars is not None and (
        isinstance(max_bars, bool) or not isinstance(max_bars, int) or max_bars < 1
    ):
        raise ValueError("Invalid max_bars")
    return float(fee), float(slip), stop, target, max_bars


def reference_replay(candles: Iterable[Any], signals: Iterable[Any], config: Any) -> list[dict[str, Any]]:
    """Recalculate trades independently using explicit OHLC fill rules."""
    bars = _validated_rows(candles)
    fee, slip, stop_pct, target_pct, max_bars = _execution_parameters(config)
    ordered = sorted(
        list(signals),
        key=lambda item: (_read(item, "index"), _read(item, "strategy"), -_read(item, "direction")),
    )
    next_free: dict[str, int] = {}
    output: list[dict[str, Any]] = []

    for signal in ordered:
        index = _read(signal, "index")
        side = _read(signal, "direction")
        strategy = _read(signal, "strategy")
        if side not in (-1, 1) or not isinstance(index, int) or index < 0 or index + 1 >= len(bars):
            continue
        entry_index = index + 1
        if entry_index <= next_free.get(strategy, -1):
            continue

        raw_entry = bars[entry_index].open
        entry_fill = raw_entry * (1.0 + side * slip)
        stop_level = entry_fill * (1.0 - side * stop_pct) if stop_pct is not None else None
        target_level = entry_fill * (1.0 + side * target_pct) if target_pct is not None else None
        final_index = min(len(bars) - 1, entry_index + max_bars - 1) if max_bars else len(bars) - 1
        exit_index = None
        raw_exit = None
        reason = "OPEN"

        for cursor in range(entry_index, final_index + 1):
            bar = bars[cursor]
            op, hi, lo = bar.open, bar.high, bar.low
            if side == 1:
                if stop_level is not None and op <= stop_level:
                    exit_index, raw_exit, reason = cursor, op, "STOP_GAP"
                elif target_level is not None and op >= target_level:
                    exit_index, raw_exit, reason = cursor, target_level, "TARGET_GAP"
                elif stop_level is not None and lo <= stop_level:
                    exit_index, raw_exit, reason = cursor, stop_level, "STOP"
                elif target_level is not None and hi >= target_level:
                    exit_index, raw_exit, reason = cursor, target_level, "TARGET"
            else:
                if stop_level is not None and op >= stop_level:
                    exit_index, raw_exit, reason = cursor, op, "STOP_GAP"
                elif target_level is not None and op <= target_level:
                    exit_index, raw_exit, reason = cursor, target_level, "TARGET_GAP"
                elif stop_level is not None and hi >= stop_level:
                    exit_index, raw_exit, reason = cursor, stop_level, "STOP"
                elif target_level is not None and lo <= target_level:
                    exit_index, raw_exit, reason = cursor, target_level, "TARGET"
            if exit_index is not None:
                break

        full_horizon = entry_index + max_bars - 1 if max_bars else None
        if exit_index is None and full_horizon is not None and full_horizon < len(bars):
            exit_index = final_index
            raw_exit = bars[final_index].close
            reason = "TIME"

        if exit_index is None:
            output.append({
                "strategy": strategy, "direction": side,
                "signal_time": bars[index].timestamp,
                "entry_time": bars[entry_index].timestamp, "exit_time": None,
                "entry_price": entry_fill, "exit_price": None, "net_return": None,
                "status": "OPEN", "exit_reason": "END_OF_DATA",
            })
            next_free[strategy] = len(bars) - 1
        else:
            exit_fill = raw_exit * (1.0 - side * slip)
            gross_return = side * (exit_fill - entry_fill) / entry_fill
            total_fee = fee * (entry_fill + exit_fill) / entry_fill
            output.append({
                "strategy": strategy, "direction": side,
                "signal_time": bars[index].timestamp,
                "entry_time": bars[entry_index].timestamp,
                "exit_time": bars[exit_index].timestamp,
                "entry_price": entry_fill, "exit_price": exit_fill,
                "net_return": gross_return - total_fee,
                "status": "CLOSED", "exit_reason": reason,
            })
            next_free[strategy] = exit_index
    return output


def compare_replay(main_trades: Iterable[Any], reference_trades: Iterable[dict[str, Any]],
                   *, tolerance: float = 1e-10) -> dict[str, Any]:
    """Compare simulator output with reference replay; return explicit mismatches."""
    actual = list(main_trades)
    expected = list(reference_trades)
    mismatches: list[dict[str, Any]] = []
    if len(actual) != len(expected):
        mismatches.append({"field": "trade_count", "actual": len(actual), "expected": len(expected)})
    for position, (left, right) in enumerate(zip(actual, expected)):
        for field in _TRADE_FIELDS:
            a = _read(left, field)
            b = right[field]
            if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
                equal = math.isclose(float(a), float(b), rel_tol=tolerance, abs_tol=tolerance)
            else:
                equal = a == b
            if not equal:
                mismatches.append({"trade_index": position, "field": field, "actual": a, "expected": b})
    return {
        "status": "REFERENCE_REPLAY_MATCH" if not mismatches else "REFERENCE_REPLAY_MISMATCH",
        "main_trade_count": len(actual),
        "reference_trade_count": len(expected),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "scope": "Independent execution replay comparison; does not validate signal-generation formulas or raw market-data provenance.",
    }
