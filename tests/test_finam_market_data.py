import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from research_agent.finam_market_data import (
    FINAM_BASE,
    FinamAPIError,
    FinamMarketDataClient,
    create_access_token,
)


def bar(timestamp="2026-11-18T10:00:00Z", **overrides):
    row = {
        "timestamp": timestamp,
        "open": {"value": "100.0"},
        "high": {"value": "102.0"},
        "low": {"value": "99.0"},
        "close": {"value": "101.0"},
        "volume": {"value": "12345"},
        "is_data_snapshot": False,
    }
    row.update(overrides)
    return row


class FinamMarketDataTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 11, 18, 0, 0, tzinfo=timezone.utc)
        self.end = datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc)

    def test_authentication_posts_secret_and_returns_access_token(self):
        calls = []

        def requester(url, **kwargs):
            calls.append((url, kwargs))
            return {"token": "access-token"}

        token = create_access_token(
            "api-secret", "research-app", requester=requester
        )
        self.assertEqual(token, "access-token")
        self.assertEqual(calls[0][0], f"{FINAM_BASE}/v1/sessions")
        self.assertEqual(calls[0][1]["method"], "POST")
        self.assertEqual(calls[0][1]["body"], {
            "secret": "api-secret", "source_app_id": "research-app"
        })

    def test_authentication_rejects_missing_token(self):
        with self.assertRaises(FinamAPIError):
            create_access_token("api-secret", requester=lambda *a, **k: {})

    def test_fetch_bars_parses_decimal_wrappers_and_snapshot_flag(self):
        calls = []

        def requester(url, **kwargs):
            calls.append((url, kwargs))
            return {"symbol": "SBER@MISX", "bars": [bar()]}

        client = FinamMarketDataClient("access-token", requester=requester)
        rows = client.fetch_bars("sber@misx", "TIME_FRAME_D", self.start, self.end)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].close, 101.0)
        self.assertEqual(rows[0].volume, 12345.0)
        self.assertFalse(rows[0].is_data_snapshot)
        self.assertEqual(rows[0].timestamp.tzinfo, timezone.utc)
        parsed = urlparse(calls[0][0])
        self.assertEqual(parsed.path, "/v1/instruments/SBER@MISX/bars")
        query = parse_qs(parsed.query)
        self.assertEqual(query["timeframe"], ["TIME_FRAME_D"])
        self.assertEqual(query["interval.start_time"], ["2026-11-18T00:00:00Z"])
        self.assertEqual(query["interval.end_time"], ["2026-11-19T00:00:00Z"])
        self.assertEqual(calls[0][1]["headers"]["Authorization"], "Bearer access-token")

    def test_fetch_bars_supports_timestamp_seconds_and_numeric_decimals(self):
        row = {
            "timestamp": {"seconds": 1794996000, "nanos": 0},
            "open": 100, "high": 102, "low": 99, "close": 101, "volume": 12,
            "is_data_snapshot": True,
        }
        client = FinamMarketDataClient("token", requester=lambda *a, **k: {"symbol": "SBER@MISX", "bars": [row]})
        rows = client.fetch_bars("SBER@MISX", "TIME_FRAME_D", self.start, self.end)
        self.assertTrue(rows[0].is_data_snapshot)

    def test_missing_snapshot_metadata_is_not_coerced_to_false(self):
        row = bar()
        row.pop("is_data_snapshot")
        client = FinamMarketDataClient(
            "token", requester=lambda *a, **k: {"symbol": "SBER@MISX", "bars": [row]}
        )
        rows = client.fetch_bars("SBER@MISX", "TIME_FRAME_D", self.start, self.end)
        self.assertIsNone(rows[0].is_data_snapshot)

    def test_fetch_bars_rejects_non_boolean_snapshot_metadata(self):
        row = bar(is_data_snapshot="false")
        client = FinamMarketDataClient(
            "token", requester=lambda *a, **k: {"symbol": "SBER@MISX", "bars": [row]}
        )
        with self.assertRaises(FinamAPIError):
            client.fetch_bars("SBER@MISX", "TIME_FRAME_D", self.start, self.end)

    def test_fetch_bars_rejects_response_for_another_symbol(self):
        client = FinamMarketDataClient(
            "token", requester=lambda *a, **k: {"symbol": "GAZP@MISX", "bars": []}
        )
        with self.assertRaises(FinamAPIError):
            client.fetch_bars("SBER@MISX", "TIME_FRAME_D", self.start, self.end)

    def test_fetch_bars_rejects_missing_mic(self):
        client = FinamMarketDataClient("token", requester=lambda *a, **k: {"symbol": "SBER@MISX", "bars": []})
        with self.assertRaises(ValueError):
            client.fetch_bars("SBER", "TIME_FRAME_D", self.start, self.end)

    def test_fetch_bars_enforces_documented_lookback(self):
        client = FinamMarketDataClient("token", requester=lambda *a, **k: {"symbol": "SBER@MISX", "bars": []})
        with self.assertRaises(ValueError):
            client.fetch_bars(
                "SBER@MISX", "TIME_FRAME_H1", self.start,
                datetime(2026, 12, 19, 0, 0, tzinfo=timezone.utc),
            )

    def test_fetch_bars_requires_aware_and_ordered_interval(self):
        client = FinamMarketDataClient("token", requester=lambda *a, **k: {"symbol": "SBER@MISX", "bars": []})
        with self.assertRaises(ValueError):
            client.fetch_bars("SBER@MISX", "TIME_FRAME_D",
                              datetime(2026, 11, 18), self.end)
        with self.assertRaises(ValueError):
            client.fetch_bars("SBER@MISX", "TIME_FRAME_D", self.end, self.start)

    def test_fetch_bars_rejects_bad_ohlcv_and_duplicate_timestamps(self):
        bad = bar(high={"value": "98"})
        client = FinamMarketDataClient("token", requester=lambda *a, **k: {"symbol": "SBER@MISX", "bars": [bad]})
        with self.assertRaises(FinamAPIError):
            client.fetch_bars("SBER@MISX", "TIME_FRAME_D", self.start, self.end)

        duplicate = [bar(), bar()]
        client = FinamMarketDataClient("token", requester=lambda *a, **k: {"symbol": "SBER@MISX", "bars": duplicate})
        with self.assertRaises(FinamAPIError):
            client.fetch_bars("SBER@MISX", "TIME_FRAME_D", self.start, self.end)

    def test_d1_accepts_session_start_bar_on_inclusive_start_date(self):
        start = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
        end = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
        client = FinamMarketDataClient(
            "token",
            requester=lambda *a, **k: {
                "symbol": "SBER@MISX",
                "bars": [bar("2026-11-18T05:00:00Z")],
            },
        )
        rows = client.fetch_bars("SBER@MISX", "TIME_FRAME_D", start, end)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].timestamp, datetime(2026, 11, 18, 5, 0, tzinfo=timezone.utc))

    def test_d1_accepts_session_start_stamp_on_end_utc_date(self):
        client = FinamMarketDataClient(
            "token",
            requester=lambda *a, **k: {
                "symbol": "SBER@MISX",
                "bars": [bar("2026-11-19T05:00:00Z")],
            },
        )
        rows = client.fetch_bars("SBER@MISX", "TIME_FRAME_D", self.start, self.end)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].timestamp, datetime(2026, 11, 19, 5, 0, tzinfo=timezone.utc))

    def test_fetch_bars_rejects_d1_bars_after_end_moscow_date(self):
        client = FinamMarketDataClient(
            "token", requester=lambda *a, **k: {
                "symbol": "SBER@MISX", "bars": [bar("2026-11-20T05:00:00Z")]
            }
        )
        with self.assertRaisesRegex(FinamAPIError, r"timestamp=2026-11-20T05:00:00\+00:00"):
            client.fetch_bars("SBER@MISX", "TIME_FRAME_D", self.start, self.end)

    def test_fetch_bars_rejects_missing_response_symbol(self):
        client = FinamMarketDataClient("token", requester=lambda *a, **k: {"bars": []})
        with self.assertRaises(FinamAPIError):
            client.fetch_bars("SBER@MISX", "TIME_FRAME_D", self.start, self.end)

    def test_fetch_bars_rejects_malformed_response(self):
        client = FinamMarketDataClient("token", requester=lambda *a, **k: {})
        with self.assertRaises(FinamAPIError):
            client.fetch_bars("SBER@MISX", "TIME_FRAME_D", self.start, self.end)


if __name__ == "__main__":
    unittest.main()
