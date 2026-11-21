"""Tests for independent structural validation of the experiment lab."""
import unittest

from research_agent.independent_validator import validate_research_report
from research_agent.cli import research_exit_code


def _report():
    return {
        "date_till": "2026-11-21",
        "development_holdout_policy": {
            "holdout_start": "2026-11-20",
            "holdout_is_strictly_prospective": True,
            "candidate_set_frozen": True,
        },
        "results": {"SBER": {"status": "DATA_OR_ANALYSIS_ERROR"}},
        "experiment_lab": {
            "lab_version": "exit-policy-experiments-v1",
            "status": "EXPERIMENT_LAB_COMPLETE",
            "generated_scope": "development_history_only",
            "holdout_start": "2026-11-20",
            "hypothesis_ids": ["exit-a"],
            "hypothesis_configs": {
                "exit-a": {
                    "fee_per_side": 0.001, "slippage_per_side": 0.0005,
                    "stop_pct": 0.03, "target_pct": 0.06, "max_bars": 120,
                }
            },
            "hypothesis_count": 1,
            "entry_strategy_ids": [
                "Donchian20", "EMA20x50", "RSI14Trend50",
                "MACD12x26", "Keltner20x2ATR",
            ],
            "entry_strategy_count": 5,
            "ticker_ids": ["SBER"],
            "ticker_count": 1,
            "trials_total": 1,
            "trials_completed": 0,
            "trials_incomplete": 1,
            "multiple_testing_family_size": 5,
            "trials": [{
                "ticker": "SBER",
                "hypothesis_id": "exit-a",
                "development_bars": 10,
                "excluded_holdout_bars": 0,
                "development_data_sha256": "a" * 64,
                "execution_config": {"fee_per_side": 0.001, "slippage_per_side": 0.0005},
                "status": "INSUFFICIENT_OR_INVALID_DEVELOPMENT_DATA",
                "reason": "not enough trades",
            }],
        },
    }


class ExperimentLabIndependentAuditTests(unittest.TestCase):
    def test_consistent_lab_metadata_is_audited_without_false_failure(self):
        result = validate_research_report(_report())
        self.assertEqual(result["experiment_lab_trials_checked"], 1)
        self.assertEqual(result["experiment_lab_trials_completed"], 0)
        self.assertEqual(result["errors"], [])

    def test_missing_explicit_lab_completion_status_is_rejected(self):
        report = _report()
        del report["experiment_lab"]["status"]
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("must explicitly declare" in error for error in result["errors"]))

    def test_cli_exit_code_fails_closed_for_invalid_or_incomplete_reports(self):
        self.assertEqual(research_exit_code(
            {"independent_validation": {"status": "INDEPENDENT_VALIDATION_FAIL"}}, 44
        ), 2)
        self.assertEqual(research_exit_code(
            {"independent_validation": {"status": "INDEPENDENT_VALIDATION_INCOMPLETE"}}, 44
        ), 3)
        self.assertEqual(research_exit_code(
            {"independent_validation": {"status": "INDEPENDENT_VALIDATION_PASS"}}, 44
        ), 0)

    def test_trial_execution_config_must_match_registered_hypothesis(self):
        report = _report()
        report["experiment_lab"]["trials"][0]["execution_config"]["stop_pct"] = 0.01
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("differs from registered hypothesis config" in error for error in result["errors"]))

    def test_non_finite_hypothesis_cost_is_rejected(self):
        report = _report()
        report["experiment_lab"]["hypothesis_configs"]["exit-a"]["fee_per_side"] = float("nan")
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("invalid fee_per_side" in error for error in result["errors"]))

    def test_missing_ticker_hypothesis_combination_is_rejected(self):
        report = _report()
        report["results"]["GAZP"] = {"status": "DATA_OR_ANALYSIS_ERROR"}
        lab = report["experiment_lab"]
        lab["ticker_ids"] = ["SBER", "GAZP"]
        lab["ticker_count"] = 2
        lab["trials_total"] = 2
        lab["trials_incomplete"] = 2
        lab["multiple_testing_family_size"] = 10
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("missing ticker/hypothesis trial combinations" in error for error in result["errors"]))

    def test_holdout_bar_in_experiment_trial_is_rejected(self):
        report = _report()
        report["experiment_lab"]["trials"][0]["excluded_holdout_bars"] = 1
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("holdout bars" in error for error in result["errors"]))

    def test_inconsistent_multiple_testing_family_is_rejected(self):
        report = _report()
        report["experiment_lab"]["multiple_testing_family_size"] = 4
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("multiple_testing_family_size" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
