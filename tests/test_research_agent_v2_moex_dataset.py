import json
import tempfile
import unittest
from pathlib import Path

from research_agent.v2.moex_dataset import MOEXDatasetError, load_pre_holdout_d1
from research_agent.v2.moex_runner import run_moex_d1_research


def candle(day, close=100.0):
    return {
        "timestamp": f"{day}T00:00:00",
        "open": close, "high": close + 1, "low": close - 1,
        "close": close, "volume": 1000.0,
    }


class MOEXDatasetLoaderTests(unittest.TestCase):
    def write_artifact(self, directory, *, post_holdout=None, validation_status="PASS"):
        data = {
            "generated_at_utc": "2026-11-21T03:25:33.304483+00:00",
            "timezone": "Europe/Moscow",
            "universe": ["SBER"],
            "results": {"SBER": {"D1": {
                "source": "MOEX ISS TQBR history",
                "status": "OK",
                "candles": [candle("2026-11-18"), candle("2026-11-19")]
                + ([post_holdout] if post_holdout is not None else []),
            }}},
        }
        validation = {
            "generated_at_utc": data["generated_at_utc"],
            "status": validation_status,
            "issue_count": 0 if validation_status == "PASS" else 1,
        }
        data_path = Path(directory) / "data.json"
        validation_path = Path(directory) / "validation.json"
        data_path.write_text(json.dumps(data), encoding="utf-8")
        validation_path.write_text(json.dumps(validation), encoding="utf-8")
        return data_path, validation_path

    def test_filters_holdout_without_parsing_its_ohlcv(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid_post = {"timestamp": "2026-11-20T00:00:00", "open": "do-not-read"}
            data_path, validation_path = self.write_artifact(
                directory, post_holdout=invalid_post
            )
            result = load_pre_holdout_d1(data_path, validation_path)
        self.assertEqual(result["universe_size"], 1)
        self.assertEqual(result["total_pre_holdout_bars"], 2)
        self.assertEqual(result["post_holdout_rows_excluded"], 1)
        self.assertEqual(result["symbols"]["SBER"][-1]["timestamp"][:10], "2026-11-19")
        self.assertFalse(result["safety"]["post_holdout_ohlcv_parsed"])

    def test_rejects_failed_validation_report(self):
        with tempfile.TemporaryDirectory() as directory:
            data_path, validation_path = self.write_artifact(
                directory, validation_status="FAIL"
            )
            with self.assertRaises(MOEXDatasetError):
                load_pre_holdout_d1(data_path, validation_path)

    def test_rejects_duplicate_pre_holdout_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            data_path, validation_path = self.write_artifact(directory)
            data = json.loads(data_path.read_text(encoding="utf-8"))
            data["results"]["SBER"]["D1"]["candles"].append(candle("2026-11-19"))
            data_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(MOEXDatasetError):
                load_pre_holdout_d1(data_path, validation_path)


class MOEXResearchRunnerTests(unittest.TestCase):
    def test_global_family_includes_all_symbols_and_uses_directional_exits(self):
        symbols = {}
        for symbol in ("AAA", "BBB"):
            bars = []
            for i in range(100):
                close = 100.0 + (i % 9) * 0.4 + (i // 9) * 0.05
                bars.append({
                    "timestamp": f"2025-01-{1 + i // 20:02d}T{(i % 20):02d}:00:00",
                    "open": close - (0.2 if i % 2 else -0.2),
                    "high": close + 1.0, "low": close - 1.0,
                    "close": close, "volume": 1000.0 + i,
                })
            symbols[symbol] = bars
        dataset = {
            "generated_at_utc": "2026-11-21T03:25:33+00:00",
            "holdout_start": "2026-11-20",
            "universe_size": 2,
            "total_pre_holdout_bars": 200,
            "post_holdout_rows_excluded": 0,
            "validation": {"status": "PASS", "issue_count": 0},
            "symbols": symbols,
        }
        result = run_moex_d1_research(
            dataset, max_hypotheses_per_symbol=4, resamples=999,
            commission_rate=0, slippage_rate=0,
        )
        self.assertEqual(result["summary"]["symbols_processed"], 2)
        self.assertEqual(
            result["summary"]["hypotheses_in_global_family"],
            result["global_family"]["family_size"],
        )
        self.assertTrue(result["safety"]["global_multiple_testing_applied"])
        self.assertFalse(result["safety"]["post_holdout_ohlcv_used"])
        self.assertEqual(result["research_design"]["strategy_approval"], "NOT_APPROVED")


if __name__ == "__main__":
    unittest.main()
