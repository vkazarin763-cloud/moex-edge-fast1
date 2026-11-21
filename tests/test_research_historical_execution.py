import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from research_agent.core import Signal
from research_agent.historical_execution import build_historical_execution


class HistoricalExecutionReplayTests(unittest.TestCase):
    def _report(self, *, both_stop_and_target=False):
        rows = []
        start = datetime(2026, 1, 1)
        for index in range(60):
            price = 100.0
            high = 108.0 if index == 56 and both_stop_and_target else (107.0 if index == 56 else 101.0)
            low = 90.0 if index == 56 and both_stop_and_target else 99.0
            rows.append({
                "timestamp": (start + timedelta(days=index)).isoformat(),
                "open": price,
                "high": high,
                "low": low,
                "close": 100.0,
                "volume": 1000.0,
            })
        return {
            "generated_at_utc": "2026-03-02T00:00:00+00:00",
            "results": {
                "AAA": {
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

    def test_uses_frozen_core_execution_and_excludes_t_and_cutoff(self):
        with patch(
            "research_agent.historical_execution.generate_signals",
            return_value=[Signal(55, 1, "Donchian20")],
        ):
            result = build_historical_execution(
                self._report(), cutoff_exclusive="2026-03-01"
            )

        self.assertEqual(result["universe_size_used"], 1)
        self.assertIn("T", result["skipped_symbols"])
        self.assertEqual(result["signal_count"], 1)
        self.assertEqual(result["summary"]["closed_trades"], 1)
        self.assertEqual(result["summary"]["open_terminal_trades"], 0)
        self.assertEqual(result["by_exit_reason"]["TARGET"]["closed_trades"], 1)
        self.assertEqual(result["execution_config"]["stop_pct"], 0.03)
        self.assertEqual(result["execution_config"]["target_pct"], 0.06)
        self.assertEqual(result["execution_config"]["max_bars"], 120)
        self.assertEqual(result["execution_config"]["fee_per_side"], 0.001)
        self.assertEqual(result["execution_config"]["slippage_per_side"], 0.0005)

    def test_stop_precedes_target_when_both_are_touched(self):
        with patch(
            "research_agent.historical_execution.generate_signals",
            return_value=[Signal(55, 1, "Donchian20")],
        ):
            result = build_historical_execution(
                self._report(both_stop_and_target=True),
                cutoff_exclusive="2026-03-01",
            )
        self.assertEqual(result["by_exit_reason"]["STOP"]["closed_trades"], 1)
        self.assertNotIn("TARGET", result["by_exit_reason"])

    def test_invalid_cutoff_is_rejected(self):
        with self.assertRaises(ValueError):
            build_historical_execution(self._report(), cutoff_exclusive="not-a-date")


if __name__ == "__main__":
    unittest.main()
