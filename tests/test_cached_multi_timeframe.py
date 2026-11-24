import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_agent.cached_multi_timeframe import (
    CachedFinamClient, load_cache, save_cache,
)
from research_agent.finam_market_data import FinamBar


class FakeClient:
    def __init__(self, bars):
        self.bars = bars
        self.calls = []

    def fetch_bars(self, symbol, timeframe, start, end):
        self.calls.append((symbol, timeframe, start, end))
        return [bar for bar in self.bars if start <= bar.timestamp < end]


def bar(hour, close):
    stamp = datetime(2026, 11, 24, hour, 0, tzinfo=timezone.utc)
    return FinamBar(stamp, close, close + 1, close - 1, close, 1000, False)


class CachedFinamClientTests(unittest.TestCase):
    def test_first_request_is_full_and_second_request_is_incremental_with_dedup(self):
        start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        end = datetime(2026, 11, 25, tzinfo=timezone.utc)
        cache = {"schema_version": 1, "bars": {}}
        first_source = FakeClient([bar(10, 100), bar(11, 101)])
        first = CachedFinamClient(first_source, cache)
        initial = first.fetch_bars("SBER@MISX", "TIME_FRAME_H1", start, end)
        self.assertEqual(len(initial), 2)
        self.assertEqual(first.stats["full_requests"], 1)

        corrected = bar(11, 102)
        added = bar(12, 103)
        second_source = FakeClient([corrected, added])
        second = CachedFinamClient(second_source, cache)
        merged = second.fetch_bars("SBER@MISX", "TIME_FRAME_H1", start, end)

        self.assertEqual(second_source.calls[0][2], datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(len(merged), 3)
        self.assertEqual([item.timestamp for item in merged],
                         sorted({item.timestamp for item in merged}))
        self.assertEqual(merged[1].close, 102)
        self.assertEqual(second.stats["incremental_requests"], 1)
        self.assertEqual(second.stats["overlap_corrections"], 1)

    def test_full_refresh_ignores_cached_rows(self):
        start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        end = datetime(2026, 11, 25, tzinfo=timezone.utc)
        cache = {"schema_version": 1, "bars": {"SBER@MISX": {
            "TIME_FRAME_H1": [{
                "timestamp": "2026-11-24T10:00:00+00:00",
                "open": 100, "high": 101, "low": 99, "close": 100,
                "volume": 1000, "is_data_snapshot": False,
            }]
        }}}
        source = FakeClient([bar(11, 101)])
        client = CachedFinamClient(source, cache, full_refresh=True)
        rows = client.fetch_bars("SBER@MISX", "TIME_FRAME_H1", start, end)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].timestamp, bar(11, 101).timestamp)
        self.assertEqual(source.calls[0][2], start)
        self.assertEqual(client.stats["full_requests"], 1)

    def test_cache_round_trip_and_corrupt_cache_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "cache.json"
            cache = {"schema_version": 1, "bars": {"SBER@MISX": {
                "TIME_FRAME_H1": [{
                    "timestamp": "2026-11-24T10:00:00+00:00",
                    "open": 100, "high": 101, "low": 99, "close": 100,
                    "volume": 1000, "is_data_snapshot": False,
                }]
            }}}
            save_cache(path, cache)
            self.assertEqual(len(load_cache(path)["bars"]["SBER@MISX"]["TIME_FRAME_H1"]), 1)
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(load_cache(path)["bars"], {})


if __name__ == "__main__":
    unittest.main()
