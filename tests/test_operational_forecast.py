import unittest
from datetime import date, datetime, timedelta, timezone

from research_agent.direction_forecast import HORIZONS, TICKERS
from research_agent.operational_forecast import build_operational_forecast


def _fixture():
    generated = "2026-11-24T00:00:00+00:00"
    results = {}
    for ticker_index, ticker in enumerate(TICKERS):
        candles = []
        price = 100.0 + ticker_index
        start = date(2026, 8, 15)
        for index in range(100):
            day = start + timedelta(days=index)
            price *= 1.002 if index % 4 else 0.997
            open_price = price * (0.999 if index % 2 else 1.001)
            candles.append({
                "timestamp": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).isoformat(),
                "open": open_price,
                "high": max(open_price, price) * 1.01,
                "low": min(open_price, price) * 0.99,
                "close": price,
                "volume": 1000.0 + (index % 9) * 25,
                "is_data_snapshot": False,
            })
        results[ticker] = {
            "D1": {
                "source": "Finam", "status": "OK", "completed_bars": len(candles),
                "candles": candles,
            }
        }
    candles_report = {
        "generated_at_utc": generated,
        "universe": list(TICKERS),
        "timeframes": {
            "D1": {"symbols": len(TICKERS), "ok": len(TICKERS),
                   "errors": 0, "no_completed_bars": 0}
        },
        "results": results,
    }
    validation_report = {
        "generated_at_utc": generated,
        "as_of_utc": generated,
        "status": "PASS",
        "issue_count": 0,
    }
    return candles_report, validation_report


class OperationalForecastTests(unittest.TestCase):
    def test_inference_uses_current_bars_but_never_post_holdout_outcomes(self):
        candles, validation = _fixture()
        report = build_operational_forecast(candles, validation)

        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(report["symbols_with_forecasts"], len(TICKERS))
        self.assertEqual(report["forecast_count"], len(TICKERS) * len(HORIZONS))
        policy = report["holdout_policy"]
        self.assertGreater(policy["post_holdout_observations_used_as_inference_inputs"], 0)
        self.assertEqual(policy["post_holdout_outcomes_used_for_training"], 0)
        self.assertEqual(policy["post_holdout_outcomes_used_for_model_selection"], 0)
        self.assertEqual(policy["post_holdout_outcomes_used_for_calibration"], 0)
        self.assertEqual(policy["post_holdout_outcomes_used_for_performance_metrics"], 0)
        self.assertTrue(policy["inference_parameters_frozen_before_holdout"])

        keys = {(item["ticker"], item["horizon_sessions"]) for item in report["forecasts"]}
        self.assertEqual(keys, {(ticker, horizon) for ticker in TICKERS for horizon in HORIZONS})
        for item in report["forecasts"]:
            self.assertEqual(item["status"], "EXPERIMENTAL_NOT_CALIBRATED")
            self.assertEqual(item["model_version"], report["model_version"])
            self.assertFalse(item["post_holdout_outcomes_used"])
            probabilities = [
                item["probability_down"], item["probability_sideways"], item["probability_up"]
            ]
            self.assertAlmostEqual(sum(probabilities), 1.0, places=8)
            self.assertTrue(all(0.0 <= value <= 1.0 for value in probabilities))

    def test_partial_history_never_claims_complete_forecast_coverage(self):
        candles, validation = _fixture()
        candles["results"][TICKERS[0]]["D1"]["candles"] = (
            candles["results"][TICKERS[0]]["D1"]["candles"][:59]
        )
        report = build_operational_forecast(candles, validation)
        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["symbols_with_valid_d1_history"], len(TICKERS) - 1)
        self.assertEqual(report["symbols_with_forecasts"], len(TICKERS) - 1)
        self.assertEqual(len(report["missing_forecasts"]), len(HORIZONS))

    def test_rejects_nonpassing_data_validation(self):
        candles, validation = _fixture()
        validation["issue_count"] = 1
        with self.assertRaisesRegex(ValueError, "PASS validation"):
            build_operational_forecast(candles, validation)

    def test_rejects_unexpected_universe(self):
        candles, validation = _fixture()
        candles["universe"] = ["SBER"]
        with self.assertRaisesRegex(ValueError, "exact frozen 44-symbol"):
            build_operational_forecast(candles, validation)

    def test_ignores_snapshot_rows_when_completed_d1_bars_are_present(self):
        candles, validation = _fixture()
        for ticker in TICKERS:
            original = candles["results"][ticker]["D1"]["candles"]
            candles["results"][ticker]["D1"]["candles"] = [
                {**original[0], "is_data_snapshot": True}, *original
            ]
        report = build_operational_forecast(candles, validation)
        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(report["symbols_with_valid_d1_history"], len(TICKERS))

    def test_rejects_snapshot_only_d1_feed(self):
        candles, validation = _fixture()
        for ticker in TICKERS:
            candles["results"][ticker]["D1"]["candles"] = [
                {**row, "is_data_snapshot": True}
                for row in candles["results"][ticker]["D1"]["candles"]
            ]
        with self.assertRaisesRegex(ValueError, "Only 0 completed D1 bars"):
            build_operational_forecast(candles, validation)


if __name__ == "__main__":
    unittest.main()
