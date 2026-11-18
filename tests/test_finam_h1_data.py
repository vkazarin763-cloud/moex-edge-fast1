import unittest
from datetime import datetime, timezone
from decimal import Decimal

from finam_h1_data import (
    FinamCandleDataError,
    parse_closed_h1_bars,
    fetch_closed_h1_candles,
)


class FinamH1DataTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 18, 12, 30, tzinfo=timezone.utc)

    def bar(self, timestamp="2026-11-18T11:00:00Z", **overrides):
        value = {
            "timestamp": timestamp,
            "open": {"value": "100"},
            "high": {"value": "105"},
            "low": {"value": "99"},
            "close": {"value": "104"},
            "volume": {"value": "1000"},
            "is_data_snapshot": False,
        }
        value.update(overrides)
        return value

    def test_closed_h1_bar_is_parsed(self):
        result = parse_closed_h1_bars([self.bar()], now=self.now)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["open"], Decimal("100"))
        self.assertEqual(result[0]["timestamp"], "2026-11-18T11:00:00+00:00")

    def test_incomplete_and_snapshot_bars_are_excluded(self):
        bars = [
            self.bar(timestamp="2026-11-18T12:00:00Z"),
            self.bar(timestamp="2026-11-18T11:00:00Z", is_data_snapshot=True),
        ]
        self.assertEqual(parse_closed_h1_bars(bars, now=self.now), [])

    def test_future_bar_is_excluded(self):
        self.assertEqual(
            parse_closed_h1_bars([self.bar("2026-11-18T13:00:00Z")], now=self.now),
            [],
        )

    def test_duplicates_are_removed_and_sorted(self):
        bars = [
            self.bar("2026-11-18T10:00:00Z"),
            self.bar("2026-11-18T11:00:00Z"),
            self.bar("2026-11-18T11:00:00Z"),
        ]
        result = parse_closed_h1_bars(bars, now=self.now)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["timestamp"], "2026-11-18T10:00:00+00:00")

    def test_bad_ohlc_fails_closed(self):
        with self.assertRaises(FinamCandleDataError):
            parse_closed_h1_bars(
                [self.bar(high={"value": "98"})], now=self.now
            )

    def test_naive_timestamp_fails_closed(self):
        with self.assertRaises(FinamCandleDataError):
            parse_closed_h1_bars(
                [self.bar("2026-11-18T11:00:00")], now=self.now
            )

    def test_fetch_uses_authenticated_h1_endpoint_and_params(self):
        captured = {}
        def fake_get(url, token, params=None):
            captured.update(url=url, token=token, params=params)
            return {"bars": [self.bar()]}
        result = fetch_closed_h1_candles(
            "jwt", "T@MISX", fake_get, now=self.now, days=7
        )
        self.assertEqual(len(result), 1)
        self.assertIn("/v1/instruments/T@MISX/bars", captured["url"])
        self.assertEqual(captured["params"]["timeframe"], "TIME_FRAME_H1")

    def test_missing_bars_array_fails_closed(self):
        with self.assertRaises(FinamCandleDataError):
            fetch_closed_h1_candles(
                "jwt", "T@MISX", lambda *a, **k: {}, now=self.now
            )


if __name__ == "__main__":
    unittest.main()
