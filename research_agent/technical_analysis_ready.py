"""Deterministic, research-only technical analysis adapter for MOEX OHLCV.

This module wraps the community-maintained pandas-ta-classic library for
candlestick patterns and standard indicators. Support/resistance clustering
and regression channels are deliberately kept as small, auditable functions.

It reports descriptive features only: it does not create LONG/SHORT signals,
place orders, size positions, or claim profitability.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd

try:
    import pandas_ta_classic  # noqa: F401  # registers the DataFrame .ta accessor
    _TA_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - environment-dependent import guard
    _TA_IMPORT_ERROR = exc


PATTERNS = (
    "engulfing",
    "hammer",
    "shootingstar",
    "morningstar",
    "eveningstar",
    "doji",
    "inside",
)


def _normalise_and_validate(candles: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(candles, pd.DataFrame):
        raise TypeError("candles must be a pandas DataFrame")
    aliases = {str(column).strip().lower(): column for column in candles.columns}
    required = ("timestamp", "open", "high", "low", "close", "volume")
    missing = [name for name in required if name not in aliases]
    if missing:
        raise ValueError(f"missing required OHLCV columns: {missing}")

    frame = pd.DataFrame({
        name: candles[aliases[name]].copy()
        for name in required
    })
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise")
    for name in ("open", "high", "low", "close", "volume"):
        frame[name] = pd.to_numeric(frame[name], errors="raise")

    if frame.empty:
        raise ValueError("candles are empty")
    if frame["timestamp"].duplicated().any():
        raise ValueError("duplicate candle timestamps")
    if not frame["timestamp"].is_monotonic_increasing:
        raise ValueError("candle timestamps must be strictly increasing")
    if not np.isfinite(frame[["open", "high", "low", "close", "volume"]].to_numpy()).all():
        raise ValueError("OHLCV contains non-finite values")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (frame["volume"] < 0).any():
        raise ValueError("volume cannot be negative")
    invalid = (
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
    )
    if invalid.any():
        raise ValueError(f"invalid OHLC relationships: {int(invalid.sum())} rows")
    return frame.reset_index(drop=True)


def _confirmed_pivots(frame: pd.DataFrame, left: int, right: int) -> list[dict[str, Any]]:
    """Return pivots only when their right-side confirmation bars have closed."""
    if left < 1 or right < 1:
        raise ValueError("left and right pivot windows must be >= 1")
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    pivots: list[dict[str, Any]] = []
    for i in range(left, len(frame) - right):
        high_window = highs[i - left:i + right + 1]
        low_window = lows[i - left:i + right + 1]
        if highs[i] == np.max(high_window) and np.count_nonzero(high_window == highs[i]) == 1:
            pivots.append({
                "kind": "resistance",
                "pivot_index": i,
                "confirmed_index": i + right,
                "timestamp": frame.iloc[i]["timestamp"].isoformat(),
                "confirmed_at": frame.iloc[i + right]["timestamp"].isoformat(),
                "price": float(highs[i]),
            })
        if lows[i] == np.min(low_window) and np.count_nonzero(low_window == lows[i]) == 1:
            pivots.append({
                "kind": "support",
                "pivot_index": i,
                "confirmed_index": i + right,
                "timestamp": frame.iloc[i]["timestamp"].isoformat(),
                "confirmed_at": frame.iloc[i + right]["timestamp"].isoformat(),
                "price": float(lows[i]),
            })
    return pivots


def _cluster_levels(
    pivots: list[dict[str, Any]], *, tolerance: float, last_close: float
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pivot in pivots:
        groups[pivot["kind"]].append(pivot)

    levels: list[dict[str, Any]] = []
    for kind, items in groups.items():
        clusters: list[list[dict[str, Any]]] = []
        for item in sorted(items, key=lambda value: value["price"]):
            if not clusters:
                clusters.append([item])
                continue
            center = float(np.median([entry["price"] for entry in clusters[-1]]))
            if abs(item["price"] - center) <= tolerance:
                clusters[-1].append(item)
            else:
                clusters.append([item])
        for cluster in clusters:
            price = float(np.median([item["price"] for item in cluster]))
            levels.append({
                "kind": kind,
                "price": price,
                "touches": len(cluster),
                "distance_pct_from_close": price / last_close - 1.0,
                "first_pivot_at": cluster[0]["timestamp"],
                "last_confirmed_at": max(item["confirmed_at"] for item in cluster),
                "pivot_timestamps": [item["timestamp"] for item in cluster],
            })
    return sorted(levels, key=lambda item: (abs(item["distance_pct_from_close"]), item["kind"]))


def _regression_channel(frame: pd.DataFrame, window: int = 60) -> dict[str, Any] | None:
    """Fit separate OLS lines to highs/lows using only the trailing completed window."""
    if window < 10 or len(frame) < window:
        return None
    sample = frame.tail(window)
    x = np.arange(window, dtype=float)
    high_slope, high_intercept = np.polyfit(x, sample["high"].to_numpy(dtype=float), 1)
    low_slope, low_intercept = np.polyfit(x, sample["low"].to_numpy(dtype=float), 1)
    upper_now = float(high_slope * (window - 1) + high_intercept)
    lower_now = float(low_slope * (window - 1) + low_intercept)
    close = float(sample.iloc[-1]["close"])
    if lower_now >= upper_now or close <= 0:
        return None
    slope_gap_pct = abs(float(high_slope - low_slope)) / close
    mean_slope_pct = (float(high_slope + low_slope) / 2.0) / close
    if slope_gap_pct > 0.01:
        channel_type = "DIVERGING_OR_UNSTABLE"
    elif mean_slope_pct > 0.00005:
        channel_type = "UP"
    elif mean_slope_pct < -0.00005:
        channel_type = "DOWN"
    else:
        channel_type = "SIDEWAYS"
    return {
        "method": "OLS_HIGH_LOW_TRAILING_WINDOW",
        "window_bars": window,
        "channel_type": channel_type,
        "upper_at_last_close": upper_now,
        "lower_at_last_close": lower_now,
        "width_pct_of_close": (upper_now - lower_now) / close,
        "upper_slope_per_bar": float(high_slope),
        "lower_slope_per_bar": float(low_slope),
        "slope_gap_pct_of_close": slope_gap_pct,
        "window_start": sample.iloc[0]["timestamp"].isoformat(),
        "window_end": sample.iloc[-1]["timestamp"].isoformat(),
    }


def analyze_ohlcv(
    candles: pd.DataFrame,
    *,
    pivot_left: int = 3,
    pivot_right: int = 3,
    channel_window: int = 60,
    level_tolerance_atr: float = 0.5,
) -> dict[str, Any]:
    """Calculate descriptive TA features from completed OHLCV bars only."""
    frame = _normalise_and_validate(candles)
    if _TA_IMPORT_ERROR is not None:
        raise RuntimeError(
            "pandas-ta-classic is required; install requirements-ta-research.txt"
        ) from _TA_IMPORT_ERROR

    # The library operates on the same OHLCV columns after strict validation.
    ta_frame = frame[["open", "high", "low", "close", "volume"]].copy()
    ta_frame.ta.ema(length=20, append=True)
    ta_frame.ta.ema(length=50, append=True)
    ta_frame.ta.ema(length=200, append=True)
    ta_frame.ta.rsi(length=14, append=True)
    ta_frame.ta.atr(length=14, append=True)
    ta_frame.ta.adx(length=14, append=True)
    ta_frame.ta.sma(close="volume", length=20, append=True, col_names=("VOL_SMA_20",))
    patterns = ta_frame.ta.cdl_pattern(name=list(PATTERNS))

    last = ta_frame.iloc[-1]
    candle_patterns: list[dict[str, Any]] = []
    if patterns is not None and not patterns.empty:
        for column, value in patterns.iloc[-1].items():
            if pd.notna(value) and float(value) != 0:
                candle_patterns.append({
                    "pattern": str(column),
                    "library_value": float(value),
                    "direction_hint": "BULLISH" if float(value) > 0 else "BEARISH",
                })

    atr = float(last.get("ATRr_14", np.nan))
    if not np.isfinite(atr) or atr <= 0:
        atr = float((frame["high"] - frame["low"]).tail(14).mean())
    tolerance = max(atr * level_tolerance_atr, float(last["close"]) * 0.001)
    pivots = _confirmed_pivots(frame, pivot_left, pivot_right)
    levels = _cluster_levels(pivots, tolerance=tolerance, last_close=float(last["close"]))
    vol_mean = float(last.get("VOL_SMA_20", np.nan))
    relative_volume = float(last["volume"] / vol_mean) if np.isfinite(vol_mean) and vol_mean > 0 else None

    def finite_or_none(value: Any) -> float | None:
        try:
            number = float(value)
            return number if np.isfinite(number) else None
        except (TypeError, ValueError):
            return None

    indicators = {
        "ema_20": finite_or_none(last.get("EMA_20")),
        "ema_50": finite_or_none(last.get("EMA_50")),
        "ema_200": finite_or_none(last.get("EMA_200")),
        "rsi_14": finite_or_none(last.get("RSI_14")),
        "atr_14": finite_or_none(last.get("ATRr_14")),
        "adx_14": finite_or_none(last.get("ADX_14")),
        "relative_volume_20": relative_volume,
    }
    return {
        "schema_version": "1.0",
        "analysis_mode": "DESCRIPTIVE_ONLY_NO_TRADING_SIGNALS",
        "last_completed_bar": frame.iloc[-1]["timestamp"].isoformat(),
        "bars_received": len(frame),
        "candlestick_patterns": candle_patterns,
        "indicators": indicators,
        "levels": {
            "method": "CONFIRMED_SWING_PIVOTS_CLUSTERED_BY_ATR",
            "pivot_left": pivot_left,
            "pivot_right": pivot_right,
            "right_side_confirmation_required": True,
            "cluster_tolerance": tolerance,
            "confirmed_pivot_count": len(pivots),
            "zones": levels,
        },
        "channel": _regression_channel(frame, channel_window),
        "limitations": [
            "Candlestick pattern names are library detections, not validated trading edges.",
            "Levels use confirmed pivots; a pivot is unavailable until its right-side bars have closed.",
            "Channel is a descriptive trailing-window OLS fit, not a guaranteed price boundary.",
            "No future bars, live data, orders, position sizing or profitability claims are used.",
        ],
    }
