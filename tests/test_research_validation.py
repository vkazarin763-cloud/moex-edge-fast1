import unittest
from unittest.mock import patch
from datetime import datetime, timedelta

from research_agent.core import Candle, BacktestConfig
from research_agent.validation import walk_forward_report, adversarial_cost_check


class WalkForwardTests(unittest.TestCase):
    def test_chronological_folds_and_small_sample_rejected(self):
        rows = []
        start = datetime(2024, 1, 1)
        for i in range(320):
            price = 100 + i * 0.2
            rows.append(Candle(start + timedelta(hours=i), price, price + 0.5,
                               price - 0.5, price, 1000))
        report = walk_forward_report(
            rows, folds=3, warmup_bars=60, min_total_trades=1,
            min_trades_per_fold=0,
            config=BacktestConfig(0, 0, None, None, 2),
        )
        self.assertEqual(len(report["folds"]), 3)
        self.assertEqual(set(report["by_direction"]), {"LONG", "SHORT"})
        for fold in report["folds"]:
            self.assertEqual(set(fold["by_direction"]), {"LONG", "SHORT"})
            for direction in ("LONG", "SHORT"):
                self.assertIsInstance(fold["by_direction"][direction], dict)
        self.assertIn(
            "not additive portfolio attribution", report["direction_scope"]
        )
        self.assertEqual(report["execution_config"], {
            "fee_per_side": 0, "slippage_per_side": 0,
            "stop_pct": None, "target_pct": None, "max_bars": 2,
        })
        starts = [f["start"] for f in report["folds"]]
        self.assertEqual(starts, sorted(starts))
        for candidate in report["candidates"].values():
            self.assertIn(candidate["status"], {
                "DEVELOPMENT_SCREEN_PASS_UNADJUSTED",
                "REJECT_OR_INSUFFICIENT_EVIDENCE",
            })

    def test_adversarial_cost_check_is_explicitly_labeled(self):
        rows = [Candle(datetime(2024, 1, 1) + timedelta(hours=i),
                       100, 101, 99, 100, 1000) for i in range(320)]
        report = adversarial_cost_check(rows, folds=2, warmup_bars=55,
                                        min_total_trades=1, min_trades_per_fold=0)
        self.assertEqual(report["stress"], "2x entry/exit fees and slippage")
        self.assertEqual(report["baseline_execution_config"], {
            "fee_per_side": 0.001, "slippage_per_side": 0.0005,
            "stop_pct": 0.03, "target_pct": 0.06, "max_bars": 120,
        })
        self.assertEqual(report["double_cost_execution_config"], {
            "fee_per_side": 0.002, "slippage_per_side": 0.001,
            "stop_pct": 0.03, "target_pct": 0.06, "max_bars": 120,
        })
        self.assertIn("does not replace", report["warning"])


    def test_supplied_baseline_is_reused_without_recalculation(self):
        baseline = {
            "execution_config": {
                "fee_per_side": 0.001, "slippage_per_side": 0.0005,
                "stop_pct": 0.03, "target_pct": 0.06, "max_bars": 120,
            },
            "candidates": {
                "Keltner20x2ATR": {
                    "status": "DEVELOPMENT_SCREEN_PASS_UNADJUSTED",
                    "average_net_return": 0.01,
                }
            },
        }
        stressed = {
            "execution_config": {
                "fee_per_side": 0.002, "slippage_per_side": 0.001,
                "stop_pct": 0.03, "target_pct": 0.06, "max_bars": 120,
            },
            "candidates": {
                "Keltner20x2ATR": {
                    "status": "DEVELOPMENT_SCREEN_PASS_UNADJUSTED",
                    "average_net_return": 0.007,
                }
            },
        }
        with patch("research_agent.validation.walk_forward_report",
                   return_value=stressed) as run_walk_forward:
            report = adversarial_cost_check(
                [], folds=2, warmup_bars=55, baseline_report=baseline
            )
        run_walk_forward.assert_called_once()
        self.assertTrue(
            report["candidates"]["Keltner20x2ATR"]["survives_double_costs"]
        )

    def test_double_cost_survival_requires_baseline_screen_pass(self):
        baseline = {
            "candidates": {
                "Keltner20x2ATR": {
                    "status": "REJECT_OR_INSUFFICIENT_EVIDENCE",
                    "average_net_return": 0.01,
                }
            }
        }
        stressed = {
            "candidates": {
                "Keltner20x2ATR": {
                    "status": "DEVELOPMENT_SCREEN_PASS_UNADJUSTED",
                    "average_net_return": 0.007,
                }
            }
        }
        with patch("research_agent.validation.walk_forward_report",
                   side_effect=[baseline, stressed]):
            report = adversarial_cost_check([], folds=2, warmup_bars=55)
        self.assertFalse(
            report["candidates"]["Keltner20x2ATR"]["survives_double_costs"]
        )

    def test_invalid_fold_count_rejected(self):
        rows = [Candle(datetime(2024, 1, 1) + timedelta(hours=i),
                       100, 101, 99, 100, 1000) for i in range(100)]
        with self.assertRaises(ValueError):
            walk_forward_report(rows, folds=1, warmup_bars=55)


class CrossSectionalDirectionSummaryTests(unittest.TestCase):
    def test_summary_is_descriptive_and_does_not_add_ticker_returns(self):
        from research_agent.validation import cross_sectional_direction_summary

        results = {
            "AAA": {
                "status": "ANALYZED",
                "walk_forward": {
                    "by_direction": {"SHORT": {"EMA20x50": {
                        "closed_trades": 10, "average_net_return": 0.02,
                        "adequately_sampled_folds": 4, "folds": 4,
                    }}},
                    "folds": [
                        {"by_direction": {"SHORT": {"EMA20x50": {
                            "closed_trades": 3, "average_net_return": 0.01,
                        }}}},
                        {"by_direction": {"SHORT": {"EMA20x50": {
                            "closed_trades": 2, "average_net_return": -0.01,
                        }}}},
                    ],
                },
            },
            "BBB": {
                "status": "ANALYZED",
                "walk_forward": {
                    "by_direction": {"SHORT": {"EMA20x50": {
                        "closed_trades": 30, "average_net_return": -0.01,
                        "adequately_sampled_folds": 4, "folds": 4,
                    }}},
                    "folds": [],
                },
            },
            "CCC": {
                "status": "ERROR",
                "walk_forward": {},
            },
        }
        summary = cross_sectional_direction_summary(results)
        item = summary["by_direction"]["SHORT"]["EMA20x50"]
        self.assertEqual(item["tickers_with_closed_trades"], 2)
        self.assertEqual(item["total_closed_trades"], 40)
        self.assertAlmostEqual(item["trade_weighted_average_net_return"], -0.0025)
        self.assertAlmostEqual(item["equal_weight_mean_ticker_average_net_return"], 0.005)
        self.assertEqual(item["positive_tickers"], 1)
        self.assertEqual(item["tickers_with_30plus_trades_and_all_folds_adequate"], 1)
        self.assertEqual(item["positive_ticker_folds"], 1)
        self.assertEqual(item["ticker_folds_with_trades"], 2)
        self.assertIn("Not a portfolio return", summary["scope"])


if __name__ == "__main__":
    unittest.main()
