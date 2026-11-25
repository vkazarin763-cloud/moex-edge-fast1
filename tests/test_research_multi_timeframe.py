import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from research_agent.multi_timeframe import (
    FINAM_FRAMES, ALL_FRAMES, RefreshingFinamClient,
    _finam_bar_is_complete, collect_multi_timeframe,
)
from research_agent.finam_market_data import FinamAPIError, FinamBar


class FakeFinam:
    def fetch_bars(self, symbol, timeframe, start, end):
        stamp = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)
        if timeframe == "TIME_FRAME_D":
            return [FinamBar(datetime(2026, 11, 19, 5, tzinfo=timezone.utc), 100, 102, 99, 101, 1000, False)]
        return [
            FinamBar(stamp, 100, 102, 99, 101, 1000, False),
            FinamBar(stamp.replace(hour=11), 101, 103, 100, 102, 1200, True),
            FinamBar(stamp.replace(hour=12), 102, 104, 101, 103, 900, None),
        ]


class MultiTimeframeTests(unittest.TestCase):
    def test_supported_frames_are_finam_only(self):
        self.assertEqual(set(FINAM_FRAMES), {"M1", "M5", "M15", "M30", "H1", "H2", "H4", "H8", "D1"})
        self.assertEqual(ALL_FRAMES, tuple(FINAM_FRAMES))
        self.assertNotIn("M10", ALL_FRAMES)
        self.assertNotIn("W1", ALL_FRAMES)
        self.assertNotIn("MN", ALL_FRAMES)
        self.assertNotIn("QR", ALL_FRAMES)

    def test_collection_uses_finam_only_and_filters_true_snapshots(self):
        calls = []

        class RecordingFinam:
            def fetch_bars(self, symbol, timeframe, start, end):
                calls.append((symbol, timeframe))
                return FakeFinam().fetch_bars(symbol, timeframe, start, end)

        result = collect_multi_timeframe(
            ["SBER"], api_token="not-used",
            now=datetime(2026, 11, 20, 13, tzinfo=timezone.utc),
            finam_client=RecordingFinam(),
            frames=["M15", "H1", "D1"],
        )
        sber = result["results"]["SBER"]
        self.assertEqual(sber["M15"]["source"], "Finam Trade API")
        self.assertEqual(sber["M15"]["raw_bars"], 3)
        self.assertEqual(sber["M15"]["completed_bars"], 2)
        self.assertEqual(sber["M15"]["snapshot_true_excluded"], 1)
        self.assertEqual(sber["M15"]["snapshot_unknown_retained"], 1)
        self.assertEqual(sber["D1"]["source"], "Finam Trade API")
        self.assertEqual(sber["D1"]["completed_bars"], 1)
        self.assertEqual(set(calls), {
            ("SBER@MISX", "TIME_FRAME_M15"),
            ("SBER@MISX", "TIME_FRAME_H1"),
            ("SBER@MISX", "TIME_FRAME_D"),
        })
        self.assertTrue(all(
            item["source"] == "Finam Trade API"
            for item in result["timeframes"].values()
        ))
        self.assertIn("No MOEX ISS fallback", result["methodology"]["source_policy"])

    def test_d1_h1_frame_filter_collects_only_signal_inputs(self):
        calls = []

        class RecordingFinam:
            def fetch_bars(self, symbol, timeframe, start, end):
                calls.append((symbol, timeframe))
                stamp = datetime(2026, 11, 19, 5, tzinfo=timezone.utc) if timeframe == "TIME_FRAME_D" else datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
                return [FinamBar(stamp, 100, 102, 99, 101, 1000, False)]

        result = collect_multi_timeframe(
            ["SBER"], api_token="not-used",
            now=datetime(2026, 11, 20, 13, tzinfo=timezone.utc),
            finam_client=RecordingFinam(), frames=["H1", "D1"],
        )
        self.assertEqual(result["requested_frames"], ["H1", "D1"])
        self.assertEqual(set(result["timeframes"]), {"H1", "D1"})
        self.assertEqual(set(result["results"]["SBER"]), {"H1", "D1"})
        self.assertEqual(set(calls), {
            ("SBER@MISX", "TIME_FRAME_H1"),
            ("SBER@MISX", "TIME_FRAME_D"),
        })

    def test_latest_signal_d1_collection_uses_finam_one_year_window(self):
        calls = []

        class RecordingFinam:
            def fetch_bars(self, symbol, timeframe, start, end):
                calls.append((symbol, timeframe, start, end))
                return []

        collect_multi_timeframe(
            ["SBER"], api_token="not-used",
            now=datetime(2026, 11, 20, 13, tzinfo=timezone.utc),
            frames=["D1"], finam_client=RecordingFinam(),
        )
        self.assertEqual(calls, [(
            "SBER@MISX", "TIME_FRAME_D",
            datetime(2025, 11, 20, 13, tzinfo=timezone.utc),
            datetime(2026, 11, 20, 13, tzinfo=timezone.utc),
        )])

    def test_frame_filter_rejects_unknown_or_missing_d1(self):
        common = {
            "api_token": "not-used",
            "now": datetime(2026, 11, 20, 13, tzinfo=timezone.utc),
            "finam_client": FakeFinam(),
        }
        with self.assertRaisesRegex(ValueError, "Unsupported Finam timeframes"):
            collect_multi_timeframe(["SBER"], frames=["D1", "M10"], **common)
        with self.assertRaisesRegex(ValueError, "D1 is required"):
            collect_multi_timeframe(["SBER"], frames=["H1"], **common)

    def test_failures_are_isolated_by_symbol_and_timeframe(self):
        class BrokenFinam:
            def fetch_bars(self, *args):
                raise RuntimeError("source unavailable")

        result = collect_multi_timeframe(
            ["SBER"], api_token="not-used",
            now=datetime(2026, 11, 20, 13, tzinfo=timezone.utc),
            finam_client=BrokenFinam(), frames=["M1", "D1"],
        )
        self.assertEqual(result["results"]["SBER"]["M1"]["status"], "ERROR")
        self.assertEqual(result["results"]["SBER"]["D1"]["status"], "ERROR")
        self.assertEqual(result["timeframes"]["M1"]["errors"], 1)
        self.assertEqual(result["timeframes"]["D1"]["errors"], 1)

    def test_finam_h1_is_supported_and_unfinished_intervals_are_excluded(self):
        now = datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc)
        self.assertTrue(_finam_bar_is_complete(
            datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc), "H1", now
        ))
        self.assertFalse(_finam_bar_is_complete(
            datetime(2026, 11, 20, 12, 30, tzinfo=timezone.utc), "H1", now
        ))
        self.assertFalse(_finam_bar_is_complete(
            datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc), "M1", now
        ))
        self.assertFalse(_finam_bar_is_complete(
            datetime(2026, 11, 20, 12, 0), "H1", now
        ))

    def test_finam_client_refreshes_once_after_401(self):
        class FakeClient:
            def __init__(self, should_fail):
                self.should_fail = should_fail

            def fetch_bars(self, *args):
                if self.should_fail:
                    raise FinamAPIError("Finam API returned HTTP 401")
                return ["ok"]

        clients = [FakeClient(True), FakeClient(False)]
        with patch("research_agent.multi_timeframe.FinamMarketDataClient.from_api_token",
                   side_effect=clients) as factory:
            client = RefreshingFinamClient("secret", "app-id")
            self.assertEqual(client.fetch_bars("SBER@MISX", "TIME_FRAME_M1", None, None), ["ok"])
            self.assertEqual(factory.call_count, 2)


if __name__ == "__main__":
    unittest.main()
