"""Causal cross-sectional relative-strength and market-regime features.

Features are aligned only on exact completed-bar timestamps. No forward fill,
interpolation, or future observations are used. Relative strength is measured
against the contemporaneous median return of other symbols, excluding self.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from statistics import median, pstdev
from typing import Any


class CrossSectionalFeatureError(ValueError):
    """Invalid cross-sectional OHLCV panel."""


def extract_cross_sectional_features(
    symbols: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    horizons: Sequence[int] = (5, 20),
    min_coverage_fraction: float = 0.5,
) -> dict[str, dict[str, list[float | None]]]:
    """Return per-symbol aligned features using only same-date current/past closes.

    A date receives market-wide features only when at least half of the
    requested universe (rounded up) has a valid return for that horizon.
    Relative strength excludes the symbol itself and requires the same number
    of other observations. Missing dates are never filled or synchronized by
    carrying stale values forward.
    """
    if not isinstance(symbols, Mapping) or not symbols:
        raise CrossSectionalFeatureError("symbols must be a non-empty mapping")
    if (isinstance(min_coverage_fraction, bool)
            or not isinstance(min_coverage_fraction, (int, float))
            or not math.isfinite(float(min_coverage_fraction))
            or not 0 < min_coverage_fraction <= 1):
        raise CrossSectionalFeatureError("min_coverage_fraction must be in (0, 1]")
    if (isinstance(horizons, (str, bytes)) or not isinstance(horizons, Sequence)
            or not horizons
            or any(isinstance(h, bool) or not isinstance(h, int) or h < 1 for h in horizons)):
        raise CrossSectionalFeatureError("horizons must contain positive integer bar counts")
    selected_horizons = tuple(sorted(set(horizons)))
    coverage_required = max(2, math.ceil(len(symbols) * float(min_coverage_fraction)))

    normalized: dict[str, tuple[list[str], list[float]]] = {}
    for symbol, bars in symbols.items():
        if not isinstance(symbol, str) or not symbol.strip():
            raise CrossSectionalFeatureError("symbol names must be non-empty strings")
        if isinstance(bars, (str, bytes)) or not isinstance(bars, Sequence):
            raise CrossSectionalFeatureError(f"{symbol}: bars must be a sequence")
        stamps: list[str] = []
        closes: list[float] = []
        previous = None
        for index, bar in enumerate(bars):
            if not isinstance(bar, Mapping):
                raise CrossSectionalFeatureError(f"{symbol}: row {index} must be a mapping")
            stamp = bar.get("timestamp")
            close = bar.get("close")
            if not isinstance(stamp, str) or not stamp:
                raise CrossSectionalFeatureError(f"{symbol}: row {index} has invalid timestamp")
            if previous is not None and stamp <= previous:
                raise CrossSectionalFeatureError(f"{symbol}: timestamps must be strictly increasing")
            if isinstance(close, bool) or not isinstance(close, (int, float)):
                raise CrossSectionalFeatureError(f"{symbol}: row {index} close must be numeric")
            close = float(close)
            if not math.isfinite(close) or close <= 0:
                raise CrossSectionalFeatureError(f"{symbol}: row {index} close must be positive and finite")
            stamps.append(stamp)
            closes.append(close)
            previous = stamp
        normalized[symbol] = (stamps, closes)

    # For each exact timestamp, collect only returns whose complete trailing
    # horizon exists in that symbol's own observed series.
    by_timestamp: dict[str, dict[int, dict[str, float]]] = {}
    for symbol, (stamps, closes) in normalized.items():
        for index, stamp in enumerate(stamps):
            for horizon in selected_horizons:
                if index < horizon:
                    continue
                value = closes[index] / closes[index - horizon] - 1.0
                by_timestamp.setdefault(stamp, {}).setdefault(horizon, {})[symbol] = value

    output: dict[str, dict[str, list[float | None]]] = {}
    for symbol, (stamps, _closes) in normalized.items():
        panel: dict[str, list[float | None]] = {}
        for horizon in selected_horizons:
            panel[f"xs_relative_return_{horizon}"] = []
            panel[f"market_median_return_{horizon}"] = []
        panel["market_breadth_positive_20"] = []
        panel["market_dispersion_20"] = []

        for stamp in stamps:
            for horizon in selected_horizons:
                values = by_timestamp.get(stamp, {}).get(horizon, {})
                own = values.get(symbol)
                enough = len(values) >= coverage_required
                market_median = median(values.values()) if enough else None
                peers = [value for peer, value in values.items() if peer != symbol]
                relative = (
                    own - median(peers)
                    if own is not None and enough and len(peers) >= coverage_required - 1
                    else None
                )
                panel[f"xs_relative_return_{horizon}"].append(relative)
                panel[f"market_median_return_{horizon}"].append(market_median)

            values20 = by_timestamp.get(stamp, {}).get(20, {})
            enough20 = len(values20) >= coverage_required
            panel["market_breadth_positive_20"].append(
                sum(value > 0 for value in values20.values()) / len(values20)
                if enough20 else None
            )
            panel["market_dispersion_20"].append(
                pstdev(values20.values()) if enough20 else None
            )
        output[symbol] = panel
    return output
