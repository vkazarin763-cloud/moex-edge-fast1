import unittest
from datetime import datetime, timezone

from research_agent.multi_timeframe_validation import (
    candle_end_utc, validate_multi_timeframe_report,
)


class MultiTimeframeValidationTests(unittest.TestCase):
    def test_finam_timestamp_zones_and_interval_ends(self):
        self.assertEqual(
            candle_end_utc("2026-11-20T20:49:00+00:00", "Finam Trade API", "M1"),
            datetime(2026, 11, 20, 20, 50, tzinfo=timezone.utc),
        )
        self.assertEqual(
            candle_end_utc("2026-11-20T00:00:00+00:00", "Finam Trade API", "D1"),
            datetime(2026, 11, 20, 21, 0, tzinfo=timezone.utc),
        )
        with self.assertRaisesRegex(ValueError, "only Finam"):
            candle_end_utc("2026-11-20T23:40:00", "MOEX ISS", "M10")
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            candle_end_utc("2026-11-20T00:00:00", "Finam Trade API", "D1")

    def test_asof_snapshot_never_selects_unclosed_bar(self):
        report = {
            "generated_at_utc": "2026-11-20T21:00:00+00:00",
            "timeframes": {"H1": {}, "D1": {}},
            "results": {
                "SBER": {
                    "H1": {
                        "source": "Finam Trade API", "status": "OK",
                        "candles": [
                            {"timestamp": "2026-11-20T19:00:00+00:00",
                             "open": 100, "high": 102, "low": 99, "close": 101,
                             "volume": 1000},
                            {"timestamp": "2026-11-20T20:30:00+00:00",
                             "open": 101, "high": 103, "low": 100, "close": 102,
                             "volume": 900},
                        ],
                    },
                    "D1": {
                        "source": "Finam Trade API", "status": "OK",
                        "candles": [
                            {"timestamp": "2026-11-19T05:00:00+00:00",
                             "open": 100, "high": 102, "low": 99, "close": 101,
                             "volume": 1000},
                        ],
                    },
                }
            },
        }
        result = validate_multi_timeframe_report(report)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["latest_closed_bars"]["SBER"]["H1"]["timestamp"],
                         "2026-11-20T19:00:00+00:00")
        self.assertIsNotNone(result["latest_closed_bars"]["SBER"]["D1"])
        self.assertEqual(result["issue_count"], 1)
        self.assertEqual(result["issues"][0]["type"], "unclosed_or_future_bar")

    def test_clean_finam_report_passes(self):
        report = {
            "generated_at_utc": "2026-11-20T13:00:00+00:00",
            "timeframes": {"H1": {}},
            "results": {
                "SBER": {
                    "H1": {
                        "source": "Finam Trade API", "status": "OK",
                        "candles": [
                            {"timestamp": "2026-11-20T11:00:00+00:00",
                             "open": 100, "high": 102, "low": 99, "close": 101,
                             "volume": 1000},
                        ],
                    }
                }
            },
        }
        result = validate_multi_timeframe_report(report)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["issue_count"], 0)


    def test_daily_gap_detection_warns_without_false_failing(self):
        def bar(ts):
            return {"timestamp": ts, "open": 100, "high": 102, "low": 99,
                    "close": 101, "volume": 1000}
        report = {
            "generated_at_utc": "2026-04-20T21:00:00+00:00",
            "timeframes": {"D1": {}},
            "results": {"T": {"D1": {
                "source": "Finam Trade API", "status": "OK",
                "candles": [
                    bar("2026-04-10T05:00:00+00:00"),
                    bar("2026-04-17T05:00:00+00:00"),
                ],
            }}},
        }
        result = validate_multi_timeframe_report(report)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["issue_count"], 0)
        self.assertEqual(result["warning_count"], 1)
        warning = result["warnings"][0]
        self.assertEqual(warning["type"], "possible_d1_session_gap")
        self.assertEqual(warning["calendar_days_between"], 7)
        self.assertEqual(warning["symbol"], "T")

    def test_normal_weekend_gap_is_not_warned(self):
        def bar(ts):
            return {"timestamp": ts, "open": 100, "high": 102, "low": 99,
                    "close": 101, "volume": 1000}
        report = {
            "generated_at_utc": "2026-04-06T21:00:00+00:00",
            "timeframes": {"D1": {}},
            "results": {"SBER": {"D1": {
                "source": "Finam Trade API", "status": "OK",
                "candles": [
                    bar("2026-04-03T05:00:00+00:00"),
                    bar("2026-04-06T05:00:00+00:00"),
                ],
            }}},
        }
        result = validate_multi_timeframe_report(report)
        self.assertEqual(result["warning_count"], 0)
        self.assertEqual(result["status"], "PASS")

    def test_non_finam_source_fails_validation(self):
        report = {
            "generated_at_utc": "2026-11-20T13:00:00+00:00",
            "timeframes": {"H1": {}},
            "results": {
                "SBER": {
                    "H1": {
                        "source": "MOEX ISS", "status": "OK",
                        "candles": [
                            {"timestamp": "2026-11-20T11:00:00+00:00",
                             "open": 100, "high": 102, "low": 99, "close": 101,
                             "volume": 1000},
                        ],
                    }
                }
            },
        }
        result = validate_multi_timeframe_report(report)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["issues"][0]["type"], "non_finam_source")


if __name__ == "__main__":
    unittest.main()
