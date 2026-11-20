import unittest
from datetime import datetime, timezone

from research_agent.multi_timeframe import (
    FINAM_FRAMES, MOEX_FRAMES, collect_multi_timeframe,
)
from research_agent.core import Candle
from research_agent.finam_market_data import FinamBar


class FakeFinam:
    def fetch_bars(self, symbol, timeframe, start, end):
        stamp = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)
        return [
            FinamBar(stamp, 100, 102, 99, 101, 1000, False),
            FinamBar(stamp.replace(hour=11), 101, 103, 100, 102, 1200, True),
            FinamBar(stamp.replace(hour=12), 102, 104, 101, 103, 900, None),
        ]


class MultiTimeframeTests(unittest.TestCase):
    def test_supported_frames_are_explicit_and_disjoint(self):
        self.assertEqual(set(FINAM_FRAMES), {"M1", "M5", "M15", "M30", "H2", "H4", "H8"})
        self.assertEqual(set(MOEX_FRAMES), {"M10", "W1", "MN", "QR"})
        self.assertFalse(set(FINAM_FRAMES) & set(MOEX_FRAMES))

    def test_collection_keeps_feeds_separate_and_filters_only_true_snapshots(self):
        calls = []

        def moex_fetcher(ticker, start, end, *, interval, board):
            calls.append((ticker, interval, board))
            return [Candle(datetime(2026, 11, 19), 100, 102, 99, 101, 500)]

        result = collect_multi_timeframe(
            ["SBER"], api_token="not-used", now=datetime(2026, 11, 20, 13, tzinfo=timezone.utc),
            moex_fetcher=moex_fetcher, finam_client=FakeFinam(),
        )
        sber = result["results"]["SBER"]
        self.assertEqual(sber["M15"]["source"], "Finam")
        self.assertEqual(sber["M15"]["raw_bars"], 3)
        self.assertEqual(sber["M15"]["completed_bars"], 2)
        self.assertEqual(sber["M15"]["snapshot_true_excluded"], 1)
        self.assertEqual(sber["M15"]["snapshot_unknown_retained"], 1)
        self.assertEqual(sber["M10"]["source"], "MOEX ISS")
        self.assertEqual(len(sber["W1"]["candles"]), 1)
        self.assertEqual(len(calls), len(MOEX_FRAMES))
        self.assertEqual(result["timeframes"]["M15"]["ok"], 1)
        self.assertIn("does not modify the frozen D1", result["methodology"]["research_isolation"])

    def test_failures_are_isolated_by_symbol_and_timeframe(self):
        class BrokenFinam:
            def fetch_bars(self, *args):
                raise RuntimeError("source unavailable")

        def broken_moex(*args, **kwargs):
            raise RuntimeError("ISS unavailable")

        result = collect_multi_timeframe(
            ["SBER"], api_token="not-used", now=datetime(2026, 11, 20, 13, tzinfo=timezone.utc),
            moex_fetcher=broken_moex, finam_client=BrokenFinam(),
        )
        self.assertEqual(result["results"]["SBER"]["M1"]["status"], "ERROR")
        self.assertEqual(result["results"]["SBER"]["MN"]["status"], "ERROR")
        self.assertEqual(result["timeframes"]["M1"]["errors"], 1)
        self.assertEqual(result["timeframes"]["QR"]["errors"], 1)


if __name__ == "__main__":
    unittest.main()
