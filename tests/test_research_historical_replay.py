import unittest
from datetime import datetime, timedelta

from research_agent.core import Signal
from research_agent.historical_replay import build_historical_simulation
from unittest.mock import patch


class HistoricalReplayTests(unittest.TestCase):
    def _candles(self, count=60):
        rows = []
        start = datetime(2026, 1, 1)
        for index in range(count):
            close = 100.0 + index
            rows.append({
                "timestamp": (start + timedelta(days=index)).isoformat(),
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000.0,
            })
        return rows

    def _report(self):
        rows = self._candles()
        return {
            "generated_at_utc": "2026-03-02T00:00:00+00:00",
            "results": {
                "TEST": {
                    "D1": {
                        "source": "MOEX ISS TQBR history",
                        "status": "OK",
                        "candles": rows,
                    }
                },
                "T": {
                    "D1": {
                        "source": "MOEX ISS TQBR history",
                        "status": "OK",
                        "candles": rows,
                    }
                },
            },
        }

    def test_replay_uses_frozen_core_and_next_open(self):
        with patch(
            "research_agent.historical_replay.generate_signals",
            return_value=[Signal(55, 1, "Donchian20")],
        ):
            result = build_historical_simulation(
                self._report(), cutoff_exclusive="2026-03-01"
            )

        self.assertEqual(result["universe_size_used"], 1)
        self.assertIn("T", result["skipped_symbols"])
        self.assertEqual(result["signal_count"], 1)
        event = result["events"][0]
        self.assertEqual(event["signal_timestamp"][:10], "2026-02-25")
        self.assertEqual(event["entry_date"], "2026-02-26")
        self.assertEqual(event["entry_open"], 156.0)
        self.assertEqual(event["outcomes"]["1"]["status"], "MATURED")
        self.assertEqual(event["outcomes"]["5"]["status"], "PENDING")
        self.assertEqual(event["mfe_mae_20"]["status"], "PENDING")
        self.assertEqual(event["h1_confirmation"], "NOT_RECONSTRUCTED_HISTORICALLY")

    def test_cutoff_is_strict_and_invalid_cutoff_rejected(self):
        with self.assertRaises(ValueError):
            build_historical_simulation(self._report(), cutoff_exclusive="not-a-date")

    def test_invalid_d1_candles_fail_closed(self):
        report = self._report()
        report["results"]["TEST"]["D1"]["candles"][3]["high"] = 1.0
        with patch(
            "research_agent.historical_replay.generate_signals",
            return_value=[],
        ):
            with self.assertRaises(ValueError):
                build_historical_simulation(
                    report,
                    cutoff_exclusive="2026-03-01",
                    excluded_symbols={},
                )


if __name__ == "__main__":
    unittest.main()
