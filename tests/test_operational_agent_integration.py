import unittest

from research_agent.agent_discovery import _compact_context, run_discovery


class OperationalAgentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.scan = {
            "status": "READ_ONLY_LATEST_SIGNAL_SCAN",
            "generated_at_utc": "2026-11-24T12:00:00+00:00",
            "as_of_utc": "2026-11-24T12:00:00+00:00",
            "universe": ["SBER", "LKOH"],
            "signals": [{
                "symbol": "SBER", "direction": "LONG", "strategy": "Donchian20",
                "d1_bar_end_utc": "2026-11-23T21:00:00+00:00",
                "h1_confirmation": "CONFIRMED", "cross_strategy_conflict": False,
            }],
        }
        self.registry = {
            "summary": {"PASS": 0, "REJECT": 0, "INSUFFICIENT_DATA": 0},
            "strategies": [],
        }
        forecasts = []
        for ticker in self.scan["universe"]:
            for horizon in (1, 5, 20):
                forecasts.append({
                    "ticker": ticker, "horizon_sessions": horizon,
                    "status": "EXPERIMENTAL_NOT_CALIBRATED",
                    "model_version": "test-model-v1",
                    "post_holdout_outcomes_used": False,
                    "predicted_class": "UP",
                    "probability_down": 0.2,
                    "probability_sideways": 0.3,
                    "probability_up": 0.5,
                })
        self.forecast = {
            "report_type": "MOEX_EDGE_OPERATIONAL_DIRECTION_FORECAST_V1",
            "status": "COMPLETE",
            "model_version": "test-model-v1",
            "as_of_date": "2026-11-24",
            "forecasts": forecasts,
            "holdout_policy": {
                "holdout_start": "2026-11-20",
                "post_holdout_outcomes_used_for_training": 0,
                "post_holdout_outcomes_used_for_model_selection": 0,
                "post_holdout_outcomes_used_for_calibration": 0,
                "post_holdout_outcomes_used_for_performance_metrics": 0,
                "inference_parameters_frozen_before_holdout": True,
            },
        }

    def test_forecast_is_passed_as_read_only_context_to_all_agents(self):
        context = _compact_context(self.scan, self.registry, self.forecast)
        self.assertEqual(
            context["direction_forecast"]["by_symbol"]["SBER"]["1"]["probabilities"],
            {"DOWN": 0.2, "SIDEWAYS": 0.3, "UP": 0.5},
        )
        prompts = []

        def fake_agent(prompt, *, api_key, model):
            prompts.append(prompt)
            return {"proposals": [], "strategy_hypotheses": []}

        report, diagnostics = run_discovery(
            self.scan, self.registry, api_key="test", caller=fake_agent,
            forecast_report=self.forecast,
        )
        self.assertEqual(len(prompts), 3)
        self.assertTrue(all("0.2" in prompt and "0.3" in prompt and "0.5" in prompt for prompt in prompts))
        self.assertEqual(diagnostics["forecast_model_version"], "test-model-v1")
        self.assertEqual(diagnostics["forecast_as_of_date"], "2026-11-24")
        self.assertFalse(diagnostics["agents_can_modify_probabilities"])
        self.assertEqual(report["proposals"], [])

    def test_rejects_incomplete_forecast_coverage(self):
        incomplete = {**self.forecast, "forecasts": self.forecast["forecasts"][:-1]}
        with self.assertRaisesRegex(ValueError, "all 1/5/20-session forecasts"):
            _compact_context(self.scan, self.registry, incomplete)

    def test_rejects_post_holdout_training_claim(self):
        unsafe = {
            **self.forecast,
            "holdout_policy": {
                **self.forecast["holdout_policy"],
                "post_holdout_outcomes_used_for_training": 1,
            },
        }
        with self.assertRaisesRegex(ValueError, "frozen holdout policy"):
            _compact_context(self.scan, self.registry, unsafe)

    def test_rejects_non_normalized_probabilities(self):
        bad = {
            **self.forecast,
            "forecasts": [
                {**row, "probability_up": 0.6}
                if row["ticker"] == "SBER" and row["horizon_sessions"] == 1 else row
                for row in self.forecast["forecasts"]
            ],
        }
        with self.assertRaisesRegex(ValueError, "normalized"):
            _compact_context(self.scan, self.registry, bad)


if __name__ == "__main__":
    unittest.main()
