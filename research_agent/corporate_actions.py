"""Reference corporate-action price-basis events for audit diagnostics only.

These events are not used to alter OHLCV data. They let the raw/history
reconciliation identify price-scale differences that coincide with documented
share splits or consolidations.
"""
from __future__ import annotations

from datetime import date
import math
from typing import Any


KNOWN_SHARE_BASIS_EVENTS: dict[str, dict[str, Any]] = {
    "GMKN": {
        "effective_date": "2024-04-04",
        "history_to_current_price_factor_before_event": 100.0,
        "event": "100-for-1 share split",
        "source": "https://nornickel.com/news-and-media/press-releases-and-news/nornickel-announces-stock-split/",
    },
    "TRNFP": {
        "effective_date": "2024-02-21",
        "history_to_current_price_factor_before_event": 100.0,
        "event": "1-for-100 share split; post-split trading parameters effective 2024-02-21",
        "source": "https://www.moex.com/n67684",
    },
    "VTBR": {
        "effective_date": "2024-07-15",
        "history_to_current_price_factor_before_event": 1.0 / 5000.0,
        "event": "5000-to-1 share consolidation",
        "source": "https://www.moex.com/n71160",
    },
    "PLZL": {
        "effective_date": "2025-03-27",
        "history_to_current_price_factor_before_event": 10.0,
        "event": "10-for-1 share split; trading resumed 2025-03-27",
        "source": "https://polyus.com/ru/media/press-releases/results-of-share-split-procedure/",
    },
    "T": {
        "effective_date": "2026-04-17",
        "history_to_current_price_factor_before_event": 10.0,
        "event": "10-for-1 share split/conversion; trading resumed 2026-04-17",
        "source": "https://t-technologies.ru/ar2025t-technologies/index.html; https://www.moex.com/n99222",
    },
}


def classify_history_to_raw_price_factor(
    ticker: str | None,
    trade_date: date,
    observed_factor: float,
) -> dict[str, Any]:
    """Classify a constant history/raw OHLC ratio without changing source values."""
    event = KNOWN_SHARE_BASIS_EVENTS.get((ticker or "").upper())
    result: dict[str, Any] = {
        "classification": "UNEXPLAINED_PRICE_SCALE_DIFFERENCE",
        "known_event": None,
        "effective_date": None,
        "expected_history_to_raw_price_factor": None,
        "source": None,
    }
    if event is None:
        result["classification"] = "NO_KNOWN_CORPORATE_ACTION_REFERENCE"
        return result

    effective = date.fromisoformat(event["effective_date"])
    result.update({
        "known_event": event["event"],
        "effective_date": event["effective_date"],
        "expected_history_to_raw_price_factor": event[
            "history_to_current_price_factor_before_event"
        ],
        "source": event["source"],
    })
    documented_factor = float(event["history_to_current_price_factor_before_event"])
    if trade_date < effective:
        if math.isclose(
            observed_factor, documented_factor, rel_tol=1e-6, abs_tol=1e-10
        ):
            result["classification"] = "MATCHES_KNOWN_PRE_EVENT_PRICE_BASIS"
            result["matched_ratio_direction"] = "DOCUMENTED_FACTOR"
        elif math.isclose(
            observed_factor, 1.0 / documented_factor,
            rel_tol=1e-6, abs_tol=1e-10,
        ):
            result["classification"] = "MATCHES_KNOWN_PRE_EVENT_PRICE_BASIS"
            result["matched_ratio_direction"] = "RECIPROCAL_DOCUMENTED_FACTOR"
    return result



def apply_post_event_price_basis(
    ticker: str, candles: list[Any], *, minimum_development_bars: int = 200,
) -> tuple[list[Any], dict[str, Any]]:
    """Keep only same-share-basis candles for historical model calculations.

    Raw source candles are retained separately for reconciliation. Known
    corporate-action events are never back-adjusted here: pre-event candles are
    excluded so indicators, walk-forward folds and experiment trials cannot
    mix incompatible share units.
    """
    symbol = (ticker or "").upper()
    event = KNOWN_SHARE_BASIS_EVENTS.get(symbol)
    if event is None:
        return list(candles), {
            "status": "NO_KNOWN_CORPORATE_ACTION",
            "ticker": symbol,
            "excluded_pre_event_bars": 0,
            "post_event_bars": len(candles),
            "minimum_development_bars": minimum_development_bars,
        }

    effective = date.fromisoformat(event["effective_date"])
    eligible = [
        candle for candle in candles
        if candle.timestamp.date() >= effective
    ]
    excluded = len(candles) - len(eligible)
    development_count = sum(
        candle.timestamp.date() < date.fromisoformat("2026-11-20")
        for candle in eligible
    )
    metadata = {
        "status": (
            "ELIGIBLE_POST_EVENT_HISTORY"
            if development_count >= minimum_development_bars
            else "INSUFFICIENT_POST_ACTION_HISTORY"
        ),
        "ticker": symbol,
        "event": event["event"],
        "effective_date": effective.isoformat(),
        "source": event["source"],
        "pre_event_bars_excluded": excluded,
        "post_event_bars": len(eligible),
        "post_event_development_bars": development_count,
        "minimum_development_bars": minimum_development_bars,
        "price_adjustment_applied": False,
        "policy": "EXCLUDE_PRE_EVENT_BARS_NO_BACK_ADJUSTMENT",
    }
    return eligible, metadata
