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
        self.assertFalse(registry["coverage"]["coverage_complete"])
        self.assertEqual(registry["coverage"]["expected_symbols"], 2)
        self.assertEqual(registry["coverage"]["analyzed_symbols"], 1)
        self.assertEqual(registry["scanner_contract"]["consume_only_status"], "BLOCKED_INCOMPLETE_COVERAGE")
        self.assertEqual(registry["summary"]["PASS"], 1)
        self.assertEqual(registry["summary"]["INSUFFICIENT_DATA"], 19)

    def test_complete_universe_coverage_keeps_registry_consumable(self):
        registry = build_strategy_registry({
            "universe": ["AAA"],
            "development_holdout_policy": {"holdout_start": "2026-11-20"},
            "results": {"AAA": {"status": "ANALYZED", "walk_forward": {}, "adversarial_cost_check": {}}},
        })
        self.assertTrue(registry["coverage"]["coverage_complete"])
        self.assertEqual(registry["coverage"]["analyzed_symbols"], 1)
        self.assertEqual(registry["scanner_contract"]["consume_only_status"], "PASS")

    def test_registry_rejects_non_positive_average_or_profit_factor(self):
        base = {
            "closed_trades": 40, "folds": 4, "adequately_sampled_folds": 4,
            "status": "DEVELOPMENT_SCREEN_PASS_UNADJUSTED",
            "average_net_return": 0.01, "profit_factor": 1.2,
        }
        stress = {"survives_double_costs": True, "double_cost_average_net_return": 0.002}
        from research_agent.strategy_registry import _candidate_status
        self.assertEqual(_candidate_status({**base, "average_net_return": 0}, stress)[0], "REJECT")
        self.assertEqual(_candidate_status({**base, "profit_factor": 1.0}, stress)[0], "REJECT")
        self.assertEqual(_candidate_status(base, {**stress, "double_cost_average_net_return": -0.001})[0], "REJECT")


if __name__ == "__main__":
    unittest.main()
