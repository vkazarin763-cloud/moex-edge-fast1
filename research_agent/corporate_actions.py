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
    expected = float(event["history_to_current_price_factor_before_event"])
    if trade_date < effective and math.isclose(
        observed_factor, expected, rel_tol=1e-6, abs_tol=1e-10
    ):
        result["classification"] = "MATCHES_KNOWN_PRE_EVENT_PRICE_BASIS"
    return result
