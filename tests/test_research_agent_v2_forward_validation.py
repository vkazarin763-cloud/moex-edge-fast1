import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from research_agent.v2.moex_forward_dataset import load_formation_and_forward_d1
from research_agent.v2.moex_forward_runner import run_moex_forward_validation


def make_report(forward_count):
    start = date(2026, 9, 1)
    candles = []
    for index in range(55):
        day = start + timedelta(days=index)
        candles.append({
            "timestamp": day.isoformat() + "T00:00:00",
            "open": 100.0 + index,
            "high": 102.0 + index,
            "low": 99.0 + index,
            "close": 101.0 + index,
            "volume": 1000.0,
        })
    # The sealed row is intentionally malformed. The loader must skip it
    # without inspecting any OHLCV values.
    candles.append({
        "timestamp": "2026-11-20T00:00:00",
        "open": "SEALED",
        "high": None,
        "low": object().__class__.__name__,
        "close": float("nan"),
        "volume": -1,
    })
    for index in range(forward_count):
        day = date(2026, 11, 21) + timedelta(days=index)
        candles.append({
            "timestamp": day.isoformat() + "T00:00:00",
            "open": 160.0 + index,
            "high": 162.0 + index,
            "low": 159.0 + index,
            "close": 161.0 + index,
            "volume": 1200.0,
        })
    return {
        "generated_at_utc": "2026-12-31T12:00:00+00:00",
        "timezone": "Europe/Moscow",
        "universe": ["AAA"],
        "results": {
            "AAA": {
                "D1": {
                    "source": "MOEX ISS TQBR history",
                    "status": "OK",
                    "candles": candles,
                }
            }
        },
    }


class MOEXForwardDatasetTests(unittest.TestCase):
    def _load(self, forward_count):
        report = make_report(forward_count)
        validation = {
            "status": "PASS",
            "issue_count": 0,
            "generated_at_utc": report["generated_at_utc"],
        }
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "data.json"
            validation_path = Path(directory) / "validation.json"
            data_path.write_text(json.dumps(report), encoding="utf-8")
            validation_path.write_text(json.dumps(validation), encoding="utf-8")
            return load_formation_and_forward_d1(
                data_path, validation_path, minimum_forward_bars=20
            )

    def test_sealed_date_is_skipped_and_new_data_is_separate(self):
        dataset = self._load(20)
        self.assertTrue(dataset["ready_for_forward_evaluation"])
        self.assertEqual(dataset["sealed_date_rows_skipped_without_ohlcv_parsing"], 1)
        self.assertEqual(len(dataset["formation_symbols"]["AAA"]), 55)
        self.assertEqual(len(dataset["forward_symbols"]["AAA"]), 20)
        self.assertEqual(dataset["safety"]["sealed_date_ohlcv_parsed"], False)
        self.assertEqual(dataset["safety"]["historical_validation_tail_used"], False)

    def test_waits_until_minimum_forward_window_exists(self):
        dataset = self._load(4)
        self.assertFalse(dataset["ready_for_forward_evaluation"])
        result = run_moex_forward_validation(dataset)
        self.assertEqual(result["status"], "WAITING_FOR_FRESH_DATA")
        self.assertEqual(result["summary"]["candidates_evaluated"], 0)


if __name__ == "__main__":
    unittest.main()
