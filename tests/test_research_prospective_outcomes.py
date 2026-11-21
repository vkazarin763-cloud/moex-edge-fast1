import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from research_agent.prospective_outcomes import OutcomeLedgerError, update_prospective_outcomes

class ProspectiveOutcomeTests(unittest.TestCase):
    def _fixtures(self, *, target_hit=True):
        start = datetime(2026, 11, 20)
        candles = []
        for index in range(60):
            high = 107.0 if target_hit and index == 56 else 101.0
            candles.append({
                "timestamp": (start + timedelta(days=index)).isoformat(),
                "open": 100.0, "high": high, "low": 99.0,
                "close": 100.0, "volume": 1000.0,
            })
        signal = {
            "symbol": "AAA", "direction": "LONG", "strategy": "Donchian20",
            "d1_signal_timestamp": start.isoformat(),
            "d1_bar_end_utc": "2026-11-20T21:00:00+00:00",
            "d1_close": 100.0, "parameters": {}, "h1_confirmation": "CONFIRMED", "h1": {},
        }
        ledger_row = {
            "schema_version": 1, "event_id": "event-1",
            "cohort_version": "v1-frozen-2026-11-19",
            "first_observed_generated_at_utc": "2026-11-21T00:00:00+00:00",
            "first_observed_as_of_utc": "2026-11-20T21:00:00+00:00",
            "signal": signal,
        }
        report = {
            "generated_at_utc": "2026-11-21T22:00:00+00:00",
            "results": {"AAA": {"D1": {
                "source": "MOEX ISS TQBR history", "status": "OK", "candles": candles,
            }}},
        }
        return ledger_row, report

    def test_closed_trade_is_appended_once_and_tagged_prospective(self):
        row, report = self._fixtures()
        with tempfile.TemporaryDirectory() as temp:
            signals, outcomes = Path(temp) / "signals.jsonl", Path(temp) / "outcomes.jsonl"
            signals.write_text(json.dumps(row) + "\n", encoding="utf-8")
            first = update_prospective_outcomes(signals, report, outcomes, holdout_start=date(2026, 11, 20))
            second = update_prospective_outcomes(signals, report, outcomes, holdout_start=date(2026, 11, 20))
            self.assertEqual(first["newly_closed"], 1)
            self.assertEqual(first["total_closed"], 1)
            self.assertEqual(second["newly_closed"], 0)
            stored = json.loads(outcomes.read_text(encoding="utf-8").strip())
            self.assertEqual(stored["data_origin"], "PROSPECTIVE")
            self.assertEqual(stored["status"], "CLOSED")
            self.assertEqual(stored["exit_reason"], "TARGET")

    def test_open_trade_is_not_added_to_closed_ledger(self):
        row, report = self._fixtures(target_hit=False)
        with tempfile.TemporaryDirectory() as temp:
            signals, outcomes = Path(temp) / "signals.jsonl", Path(temp) / "outcomes.jsonl"
            signals.write_text(json.dumps(row) + "\n", encoding="utf-8")
            result = update_prospective_outcomes(signals, report, outcomes, holdout_start=date(2026, 11, 20))
            self.assertEqual(result["newly_closed"], 0)
            self.assertEqual(result["pending_open"], 1)
            self.assertFalse(outcomes.exists())

    def test_missing_signal_candle_fails_closed(self):
        row, report = self._fixtures()
        report["results"]["AAA"]["D1"]["candles"] = report["results"]["AAA"]["D1"]["candles"][1:]
        with tempfile.TemporaryDirectory() as temp:
            signals, outcomes = Path(temp) / "signals.jsonl", Path(temp) / "outcomes.jsonl"
            signals.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaises(OutcomeLedgerError):
                update_prospective_outcomes(signals, report, outcomes, holdout_start=date(2026, 11, 20))
            self.assertFalse(outcomes.exists())

if __name__ == "__main__":
    unittest.main()
