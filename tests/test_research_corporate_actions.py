"""Tests for exclusion of pre-event corporate-action price bases."""
import unittest
from datetime import datetime, timedelta

from research_agent.core import Candle
from research_agent.corporate_actions import (
    KNOWN_SHARE_BASIS_EVENTS, apply_post_event_price_basis,
)


def candles(start, count):
    first = datetime.fromisoformat(start)
    rows = []
    for i in range(count):
        dt = first + timedelta(days=i)
        rows.append(Candle(dt, 100, 101, 99, 100, 1000))
    return rows


class CorporateActionPriceBasisTests(unittest.TestCase):
    def test_all_known_events_exclude_every_pre_event_bar(self):
        for ticker, event in KNOWN_SHARE_BASIS_EVENTS.items():
            with self.subTest(ticker=ticker):
                effective = event["effective_date"]
                rows = candles("2024-01-01", 1000)
                filtered, metadata = apply_post_event_price_basis(ticker, rows)
                self.assertTrue(all(
                    row.timestamp.date().isoformat() >= effective for row in filtered
                ))
                self.assertEqual(metadata["policy"], "EXCLUDE_PRE_EVENT_BARS_NO_BACK_ADJUSTMENT")
                self.assertFalse(metadata["price_adjustment_applied"])
                self.assertEqual(
                    metadata["pre_event_bars_excluded"] + metadata["post_event_bars"],
                    len(rows),
                )

    def test_unaffected_ticker_is_unchanged(self):
        rows = candles("2024-01-01", 10)
        filtered, metadata = apply_post_event_price_basis("SBER", rows)
        self.assertEqual(filtered, rows)
        self.assertEqual(metadata["status"], "NO_KNOWN_CORPORATE_ACTION")

    def test_recent_event_with_short_development_history_is_ineligible(self):
        rows = candles("2026-04-17", 180)
        filtered, metadata = apply_post_event_price_basis("T", rows)
        self.assertEqual(len(filtered), 180)
        self.assertEqual(metadata["status"], "INSUFFICIENT_POST_ACTION_HISTORY")
        self.assertEqual(metadata["post_event_development_bars"], 180)


if __name__ == "__main__":
    unittest.main()
