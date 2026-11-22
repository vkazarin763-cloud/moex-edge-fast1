"""Point-in-time OHLCV feature extraction for autonomous research.

Every value at row t uses only the current bar and bars at or before t.
Warm-up observations are represented as None, never replaced with zero.
"""
from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Mapping, Sequence


class FeatureInputError(ValueError):
    """Raised when OHLCV bars violate the feature extractor data contract."""


def _number(bar: Mapping[str, Any], field: str, row: int) -> float:
    value = bar.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FeatureInputError(f"row {row}: {field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise FeatureInputError(f"row {row}: {field} must be finite")
    return result


def _validate_bars(bars: Sequence[Mapping[str, Any]]) -> list[dict[str, float | str]]:
    if isinstance(bars, (str, bytes)) or not isinstance(bars, Sequence) or not bars:
        raise FeatureInputError("bars must be a non-empty sequence")
    normalized: list[dict[str, float | str]] = []
    previous: datetime | None = None
    for index, source in enumerate(bars):
        if not isinstance(source, Mapping):
            raise FeatureInputError(f"row {index}: bar must be a mapping")
        timestamp = source.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp:
            raise FeatureInputError(f"row {index}: timestamp must be a non-empty ISO-8601 string")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FeatureInputError(f"row {index}: invalid ISO-8601 timestamp") from exc
        if previous is not None:
            try:
                ordered = parsed > previous
            except TypeError as exc:
                raise FeatureInputError("timestamps must use a consistent timezone convention") from exc
            if not ordered:
                raise FeatureInputError("timestamps must be strictly increasing and unique")
        previous = parsed

        values = {field: _number(source, field, index)
                  for field in ("open", "high", "low", "close", "volume")}
        o, h, low, c, volume = (values[key] for key in ("open", "high", "low", "close", "volume"))
        if min(o, h, low, c) <= 0:
            raise FeatureInputError(f"row {index}: OHLC prices must be positive")
        if h < max(o, c, low) or low > min(o, c) or h < low:
            raise FeatureInputError(f"row {index}: invalid OHLC relationship")
        if volume < 0:
            raise FeatureInputError(f"row {index}: volume must be non-negative")
        normalized.append({"timestamp": timestamp, **values})
    return normalized


def extract_ohlcv_features(
    bars: Sequence[Mapping[str, Any]],
    *,
    return_horizons: Sequence[int] = (1, 5, 10, 20),
    volume_window: int = 20,
    range_window: int = 20,
    volatility_window: int = 10,
    efficiency_window: int = 10,
) -> dict[str, list[float | None]]:
    """Build generic candle, return, volume and volatility descriptors.

    Relative-volume and range baselines use *prior* bars only. Rolling return
    volatility and efficiency include the current close-to-close return, which
    is known at the close of row t. All windows are bar-count windows, not
    calendar-day assumptions. The returned arrays align one-to-one with bars.
    """
    data = _validate_bars(bars)
    windows = {
        "volume_window": volume_window,
        "range_window": range_window,
        "volatility_window": volatility_window,
        "efficiency_window": efficiency_window,
    }
    for name, value in windows.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 2:
            raise FeatureInputError(f"{name} must be an integer >= 2")
    if isinstance(return_horizons, (str, bytes)) or not isinstance(return_horizons, Sequence) or not return_horizons:
        raise FeatureInputError("return_horizons must be a non-empty sequence")
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in return_horizons):
        raise FeatureInputError("return horizons must be positive integers")
    horizons = sorted(set(return_horizons))

    n = len(data)
    opens = [float(row["open"]) for row in data]
    highs = [float(row["high"]) for row in data]
    lows = [float(row["low"]) for row in data]
    closes = [float(row["close"]) for row in data]
    volumes = [float(row["volume"]) for row in data]
    returns: list[float | None] = [None] + [
        closes[i] / closes[i - 1] - 1.0 for i in range(1, n)
    ]
    ranges = [(highs[i] - lows[i]) / closes[i - 1] if i else None for i in range(n)]

    result: dict[str, list[float | None]] = {
        "candle_body_pct": [],
        "candle_range_pct": [],
        "upper_wick_fraction": [],
        "lower_wick_fraction": [],
        "close_location": [],
        "gap_pct": [],
        "relative_volume": [],
        "range_vs_prior_mean": [],
        "realized_volatility": [],
        "trend_efficiency": [],
    }
    for horizon in horizons:
        result[f"return_{horizon}"] = []

    for i in range(n):
        candle_range = highs[i] - lows[i]
        result["candle_body_pct"].append((closes[i] - opens[i]) / opens[i])
        result["candle_range_pct"].append(candle_range / closes[i])
        result["upper_wick_fraction"].append(
            (highs[i] - max(opens[i], closes[i])) / candle_range if candle_range else 0.0
        )
        result["lower_wick_fraction"].append(
            (min(opens[i], closes[i]) - lows[i]) / candle_range if candle_range else 0.0
        )
        result["close_location"].append(
            (closes[i] - lows[i]) / candle_range if candle_range else 0.5
        )
        result["gap_pct"].append(opens[i] / closes[i - 1] - 1.0 if i else None)

        start = i - volume_window
        prior_volumes = volumes[start:i] if start >= 0 else []
        avg_volume = sum(prior_volumes) / volume_window if len(prior_volumes) == volume_window else None
        result["relative_volume"].append(
            volumes[i] / avg_volume if avg_volume is not None and avg_volume > 0 else None
        )

        start = i - range_window
        prior_ranges = ranges[start:i] if start >= 0 else []
        prior_ranges = [v for v in prior_ranges if v is not None]
        avg_range = sum(prior_ranges) / range_window if len(prior_ranges) == range_window else None
        current_range = ranges[i]
        result["range_vs_prior_mean"].append(
            current_range / avg_range if current_range is not None and avg_range and avg_range > 0 else None
        )

        start = i - volatility_window + 1
        window_returns = returns[start:i + 1] if start >= 0 else []
        window_returns = [v for v in window_returns if v is not None]
        if len(window_returns) == volatility_window:
            mean = sum(window_returns) / volatility_window
            variance = sum((v - mean) ** 2 for v in window_returns) / volatility_window
            result["realized_volatility"].append(math.sqrt(variance))
        else:
            result["realized_volatility"].append(None)

        start = i - efficiency_window + 1
        window_returns = returns[start:i + 1] if start >= 0 else []
        window_returns = [v for v in window_returns if v is not None]
        if len(window_returns) == efficiency_window:
            path = sum(abs(v) for v in window_returns)
            result["trend_efficiency"].append(
                abs(closes[i] / closes[i - efficiency_window] - 1.0) / path if path else 0.0
            )
        else:
            result["trend_efficiency"].append(None)

        for horizon in horizons:
            result[f"return_{horizon}"].append(
                closes[i] / closes[i - horizon] - 1.0 if i >= horizon else None
            )

    return result
