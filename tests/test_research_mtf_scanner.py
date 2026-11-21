import unittest
from datetime import datetime, timedelta, timezone

from research_agent.core import Candle
from research_agent.mtf_scanner import (
    _d1_signals_at_last_bar, _h1_alignment, _parse_candles,
    scan_multi_timeframe_report,
)


class MTFScannerTests(unittest.TestCase):
    def _trend(self, count, start, step, aware=True):
        rows = []
        for i in range(count):
            close = start + step * i
            stamp = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
            rows.append(Candle(stamp, close, close + 1, close - 1, close, 1000))
        return rows

    def test_h1_alignment_long_and_short(self):
        rising = self._trend(80, 100, 1)
        falling = self._trend(80, 180, -1)
        self.assertEqual(_h1_alignment(rising, 1)["status"], "CONFIRMED")
        self.assertEqual(_h1_alignment(falling, -1)["status"], "CONFIRMED")
        self.assertEqual(_h1_alignment(rising, -1)["status"], "NOT_CONFIRMED")

    def test_h1_insufficient_history_is_explicit(self):
        result = _h1_alignment(self._trend(49, 100, 1), 1)
        self.assertEqual(result["status"], "INSUFFICIENT_HISTORY")

    def test_latest_d1_signal_uses_last_bar_and_fixed_donchian_formula(self):
        rows = self._trend(60, 100, 1)
        # Force the final close above the preceding 20-bar high.
        last = rows[-1]
        rows[-1] = Candle(last.timestamp, 180, 190, 179, 189, 1000)
        found = _d1_signals_at_last_bar(rows)
        self.assertTrue(any(x["strategy"] == "Donchian20" and x["direction"] == "LONG" for x in found))

    def test_scanner_rejects_failed_validation(self):
        with self.assertRaises(ValueError):
            scan_multi_timeframe_report({}, {"status": "FAIL", "issue_count": 1})

    def test_scanner_rejects_mismatched_snapshot(self):
        with self.assertRaises(ValueError):
            scan_multi_timeframe_report(
                {"generated_at_utc": "2026-01-01T00:00:00+00:00", "universe": [], "results": {}},
                {"status": "PASS", "issue_count": 0, "generated_at_utc": "2026-01-02T00:00:00+00:00",
                 "as_of_utc": "2026-01-02T00:00:00+00:00"},
            )

    def test_d1_naive_timestamp_is_interpreted_as_moscow(self):
        parsed = _parse_candles(
            [{"timestamp": "2026-01-01T00:00:00", "open": 10, "high": 11, "low": 9,
              "close": 10, "volume": 100}],
            source="MOEX ISS TQBR history",
        )
        self.assertEqual(parsed[0].timestamp.utcoffset(), timedelta(hours=3))

    def test_h1_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            _parse_candles(
                [{"timestamp": "2026-01-01T00:00:00", "open": 10, "high": 11, "low": 9,
                  "close": 10, "volume": 100}],
                source="Finam",
            )


if __name__ == "__main__":
    unittest.main()
