"""First single-security MOEX EDGE v2 research metrics.

This module is deliberately independent of v1. It does not fetch data, execute
orders, size positions, or approve strategies. A caller must explicitly assert
that the input price basis has been verified before a metric is eligible.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Sequence

V2_STRATEGIES = ("TSM_12_1", "HIGH_52W")
VALID_PRICE_BASES = {"verified_adjusted", "verified_same_share"}
TRADING_SESSIONS_PER_YEAR = 252
SKIP_RECENT_SESSIONS = 21


class DataContractError(ValueError):
    """Raised when bars violate the v2 single-security input contract."""


def validate_bars(bars: Sequence[dict[str, Any]]) -> None:
    if not isinstance(bars, (list, tuple)):
        raise DataContractError("bars must be a list or tuple of mappings")
    previous_timestamp = None
    for index, bar in enumerate(bars):
        if not isinstance(bar, dict):
            raise DataContractError(f"bar {index} is not a mapping")
        timestamp = bar.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp:
            raise DataContractError(f"bar {index} has no ISO timestamp string")
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DataContractError(f"bar {index} timestamp is not ISO-8601") from exc
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise DataContractError("timestamps must be strictly increasing and unique")
        previous_timestamp = timestamp
        for field in ("close", "high"):
            value = bar.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise DataContractError(f"bar {index} has invalid {field}")
            if not isfinite(float(value)) or float(value) <= 0:
                raise DataContractError(f"bar {index} has non-positive or non-finite {field}")
        if float(bar["high"]) < float(bar["close"]):
            raise DataContractError(f"bar {index} high is below close")


def _not_ready(reason: str, strategy: str) -> dict[str, Any]:
    return {
        "strategy": strategy,
        "status": "DATA_NOT_READY",
        "signal": None,
        "reason": reason,
        "metrics": {},
        "eligible_for_performance_test": False,
    }


def time_series_momentum_12_1(
    bars: Sequence[dict[str, Any]],
    *,
    price_basis_status: str = "unverified",
    formation_index: int | None = None,
) -> dict[str, Any]:
    """Return the 12-1 own-price momentum signal at a completed formation bar.

    Uses close[t-21] / close[t-252] - 1. The most recent 21 sessions are
    skipped. This is a signal primitive, not a backtest or trade instruction.
    """
    validate_bars(bars)
    if price_basis_status not in VALID_PRICE_BASES:
        return _not_ready("Corporate-action/same-share price basis is not verified", "TSM_12_1")
    end = len(bars) - 1 if formation_index is None else formation_index
    if isinstance(end, bool) or not isinstance(end, int) or end < 0 or end >= len(bars):
        raise DataContractError("formation_index is outside the supplied bars")
    lookback = TRADING_SESSIONS_PER_YEAR
    skip = SKIP_RECENT_SESSIONS
    if end < lookback:
        return {
            "strategy": "TSM_12_1",
            "status": "INSUFFICIENT_DATA",
            "signal": None,
            "reason": f"Requires {lookback + 1} bars through formation date",
            "metrics": {},
            "eligible_for_performance_test": False,
        }
    old_close = float(bars[end - lookback]["close"])
    skip_close = float(bars[end - skip]["close"])
    trailing_return = skip_close / old_close - 1.0
    signal = "LONG" if trailing_return > 0 else "SHORT" if trailing_return < 0 else "FLAT"
    return {
        "strategy": "TSM_12_1",
        "status": "READY_FOR_RESEARCH",
        "formation_timestamp": bars[end]["timestamp"],
        "signal": signal,
        "reason": "12-1 return calculated from completed bars only",
        "metrics": {
            "return_12_1": trailing_return,
            "lookback_sessions": lookback,
            "skipped_recent_sessions": skip,
        },
        "eligible_for_performance_test": True,
    }


def high_52_week_proximity(
    bars: Sequence[dict[str, Any]],
    *,
    price_basis_status: str = "unverified",
    formation_index: int | None = None,
) -> dict[str, Any]:
    """Return close / rolling 252-session high as a ranking metric.

    The design intentionally does not invent a long/short cutoff. Cross-sectional
    ranking and the portfolio selection rule belong in a separately frozen panel
    evaluator, not in this single-security primitive.
    """
    validate_bars(bars)
    if price_basis_status not in VALID_PRICE_BASES:
        return _not_ready("Corporate-action/same-share price basis is not verified", "HIGH_52W")
    end = len(bars) - 1 if formation_index is None else formation_index
    if isinstance(end, bool) or not isinstance(end, int) or end < 0 or end >= len(bars):
        raise DataContractError("formation_index is outside the supplied bars")
    window = TRADING_SESSIONS_PER_YEAR
    start = end - window + 1
    if start < 0:
        return {
            "strategy": "HIGH_52W",
            "status": "INSUFFICIENT_DATA",
            "signal": None,
            "reason": f"Requires {window} bars through formation date",
            "metrics": {},
            "eligible_for_performance_test": False,
        }
    rolling_high = max(float(bar["high"]) for bar in bars[start : end + 1])
    close = float(bars[end]["close"])
    proximity = close / rolling_high
    return {
        "strategy": "HIGH_52W",
        "status": "READY_FOR_RESEARCH",
        "formation_timestamp": bars[end]["timestamp"],
        "signal": None,
        "reason": "52-week-high proximity metric; no unregistered direction threshold applied",
        "metrics": {
            "close_to_252_session_high": proximity,
            "rolling_high": rolling_high,
            "lookback_sessions": window,
        },
        "eligible_for_performance_test": True,
    }
