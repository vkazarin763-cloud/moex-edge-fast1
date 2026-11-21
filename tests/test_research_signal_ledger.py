import json
import tempfile
import unittest
from pathlib import Path

from research_agent.signal_ledger import LedgerError, append_signal_report


def report():
    signal = {
        "symbol": "SBER", "direction": "SHORT", "strategy": "Donchian20",
        "d1_signal_timestamp": "2026-11-20T00:00:00",
        "d1_bar_end_utc": "2026-11-20T21:00:00+00:00",
        "d1_close": 250.0, "parameters": {"close": 250.0},
        "h1_confirmation": "CONFIRMED", "h1": {"h1_close": 249.0},
    }
    return {
        "status": "READ_ONLY_LATEST_SIGNAL_SCAN",
        "generated_at_utc": "2026-11-21T09:30:00+00:00",
        "as_of_utc": "2026-11-21T09:25:00+00:00",
        "strategy_cohort_version": "v1-frozen-2026-11-19",
        "signals": [signal],
    }


class SignalLedgerTests(unittest.TestCase):
    def test_first_observation_appends_and_repeat_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signals.jsonl"
            first = append_signal_report(report(), path)
            second = append_signal_report(report(), path)
            self.assertEqual(first, {"added": 1, "duplicates": 0, "total_events": 1})
            self.assertEqual(second, {"added": 0, "duplicates": 1, "total_events": 1})
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)

    def test_changed_signal_payload_for_same_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signals.jsonl"
            append_signal_report(report(), path)
            changed = report()
            changed["signals"][0]["d1_close"] = 251.0
            with self.assertRaises(LedgerError):
                append_signal_report(changed, path)

    def test_invalid_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LedgerError):
                append_signal_report({"status": "OTHER"}, Path(tmp) / "x.jsonl")

    def test_malformed_existing_ledger_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signals.jsonl"
            path.write_text("{broken\\n", encoding="utf-8")
            with self.assertRaises(LedgerError):
                append_signal_report(report(), path)
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken\\n")

    def test_conflicting_duplicate_ids_in_existing_ledger_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signals.jsonl"
            append_signal_report(report(), path)
            row = json.loads(path.read_text(encoding="utf-8"))
            row["signal"]["d1_close"] = 999
            path.write_text(path.read_text(encoding="utf-8") + json.dumps(row) + "\\n", encoding="utf-8")
            with self.assertRaises(LedgerError):
                append_signal_report(report(), path)


if __name__ == "__main__":
    unittest.main()
