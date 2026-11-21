import unittest
from datetime import datetime, timezone

from research_agent.multi_timeframe_validation import (
    candle_end_utc, validate_multi_timeframe_report,
)


class MultiTimeframeValidationTests(unittest.TestCase):
    def test_native_timestamp_zones_and_interval_ends(self):
        self.assertEqual(
            candle_end_utc("2026-11-20T20:49:00+00:00", "Finam", "M1"),
            datetime(2026, 11, 20, 20, 50, tzinfo=timezone.utc),
        )
        self.assertEqual(
            candle_end_utc("2026-11-20T23:40:00", "MOEX ISS", "M10"),
            datetime(2026, 11, 20, 20, 50, tzinfo=timezone.utc),
        )

    def test_asof_snapshot_never_selects_unclosed_bar(self):
        report = {
            "generated_at_utc": "2026-11-20T13:00:00+00:00",
            "timeframes": {"H1": {}, "M10": {}},
            "results": {
                "SBER": {
                    "H1": {
                        "source": "Finam", "status": "OK",
                        "candles": [
                            {"timestamp": "2026-11-20T11:00:00+00:00",
                             "open": 100, "high": 102, "low": 99, "close": 101,
                             "volume": 1000},
                            {"timestamp": "2026-11-20T12:30:00+00:00",
                             "open": 101, "high": 103, "low": 100, "close": 102,
                             "volume": 900},
                        ],
                    },
                    "M10": {
                        "source": "MOEX ISS", "status": "OK",
                        "candles": [
                            {"timestamp": "2026-11-20T23:40:00",
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
                         "2026-11-20T11:00:00+00:00")
        self.assertEqual(result["latest_closed_bars"]["SBER"]["M10"]["end_utc"],
                         "2026-11-20T20:50:00+00:00")
        self.assertEqual(result["issue_count"], 1)
        self.assertEqual(result["issues"][0]["type"], "unclosed_or_future_bar")

    def test_clean_report_passes(self):
        report = {
            "generated_at_utc": "2026-11-20T13:00:00+00:00",
            "timeframes": {"H1": {}},
            "results": {
                "SBER": {
                    "H1": {
                        "source": "Finam", "status": "OK",
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


if __name__ == "__main__":
    unittest.main()
