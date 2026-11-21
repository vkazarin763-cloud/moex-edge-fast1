import unittest

from research_agent.strategy_registry import build_strategy_registry


class StrategyRegistryTests(unittest.TestCase):
    def test_registry_requires_development_and_double_cost_pass(self):
        report = {
            "development_holdout_policy": {"holdout_start": "2026-11-20"},
            "results": {
                "AAA": {
                    "status": "ANALYZED",
                    "walk_forward": {"by_direction": {
                        "LONG": {"Donchian20": {
                            "closed_trades": 40, "folds": 4,
                            "adequately_sampled_folds": 4, "positive_folds": 3,
                            "average_net_return": 0.01, "profit_factor": 1.2,
                            "status": "DEVELOPMENT_SCREEN_PASS_UNADJUSTED",
                        }},
                        "SHORT": {"EMA20x50": {
                            "closed_trades": 10, "folds": 4,
                            "adequately_sampled_folds": 1, "positive_folds": 1,
                            "average_net_return": 0.02, "profit_factor": 1.4,
                            "status": "REJECT_OR_INSUFFICIENT_EVIDENCE",
                        }},
                    }},
                    "adversarial_cost_check": {"candidates": {
                        "Donchian20": {"by_direction": {
                            "LONG": {"survives_double_costs": True,
                                     "double_cost_average_net_return": 0.003}
                        }}
                    }},
                },
                "BBB": {"status": "INSUFFICIENT_POST_ACTION_HISTORY"},
            },
        }
        registry = build_strategy_registry(report)
        rows = {(x["ticker"], x["direction"], x["strategy"]): x
                for x in registry["strategies"]}
        self.assertEqual(rows[("AAA", "LONG", "Donchian20")]["status"], "PASS")
        self.assertTrue(rows[("AAA", "LONG", "Donchian20")]["eligible_for_shadow_scanner"])
        self.assertEqual(rows[("AAA", "SHORT", "EMA20x50")]["status"], "INSUFFICIENT_DATA")
        self.assertEqual(rows[("AAA", "LONG", "EMA20x50")]["status"], "INSUFFICIENT_DATA")
        self.assertEqual(rows[("BBB", "LONG", "Donchian20")]["status"], "INSUFFICIENT_DATA")
        self.assertFalse(registry["scanner_contract"]["live_trading_authorized"])
        self.assertEqual(registry["summary"]["PASS"], 1)
        self.assertEqual(registry["summary"]["INSUFFICIENT_DATA"], 44)


if __name__ == "__main__":
    unittest.main()
