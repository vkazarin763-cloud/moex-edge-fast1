"""Regression tests for the independent research-report validator."""
import unittest

from research_agent.independent_validator import validate_research_report


def _report():
    return {
        "date_till": "2026-11-20",
        "development_holdout_policy": {
            "holdout_start": "2026-11-20",
            "holdout_is_strictly_prospective": True,
            "candidate_set_frozen": True,
        },
        "results": {
            "SBER": {
                "status": "ANALYZED",
                "session_date_mapping": {
                    "positive_trade_history_dates": 2,
                    "history_dates_with_raw_fragments": 2,
                    "history_trade_dates_without_raw_fragments": 0,
                    "raw_history_date_coverage_ratio": 1.0,
                    "raw_history_coverage_status": "COMPLETE_DATE_COVERAGE",
                    "trading_days_reconciled": 2,
                    "trading_days_mismatched": 0,
                    "unassigned_raw_candles": 0,
                    "raw_candles": 2,
                    "mapped_raw_candles": 2,
                    "unassigned_reason_counts": {},
                    "mismatch_reason_counts": {},
                    "mismatch_field_counts": {
                        "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0
                    },
                    "raw_weekend_candles": 0,
                    "raw_weekend_candles_mapped": 0,
                    "raw_weekend_candles_unmapped": 0,
                    "raw_weekday_additional_session_candles": 0,
                    "raw_weekday_additional_session_candles_mapped": 0,
                    "raw_weekday_additional_session_candles_unmapped": 0,
                    "price_scale_mismatch_dates": 0,
                    "known_price_basis_match_count": 0,
                    "unexplained_price_scale_mismatch_count": 0,
                    "price_scale_factor_counts": {},
                    "complete": True,
                    "status": "RECONCILED",
                },
                "walk_forward": {
                    "folds": [
                        {"start": "2024-01-01", "end_inclusive": "2024-12-31"},
                        {"start": "2025-01-01", "end_inclusive": "2025-12-31"},
                    ]
                },
                "prospective_holdout": {"holdout_start": "2026-11-20"},
                "adversarial_cost_check": {
                    "baseline_execution_config": {
                        "fee_per_side": 0.001, "slippage_per_side": 0.0005
                    },
                    "double_cost_execution_config": {
                        "fee_per_side": 0.002, "slippage_per_side": 0.001
                    },
                    "candidates": {
                        "Donchian20": {
                            "baseline_status": "REJECT_OR_INSUFFICIENT_EVIDENCE",
                            "double_cost_status": "DEVELOPMENT_SCREEN_PASS_UNADJUSTED",
                            "double_cost_average_net_return": 0.01,
                            "survives_double_costs": False,
                        }
                    },
                },
            }
        },
    }


class IndependentValidatorTests(unittest.TestCase):
    def test_valid_structural_report_passes(self):
        result = validate_research_report(_report())
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_PASS")
        self.assertEqual(result["walk_forward_folds_checked"], 2)

    def test_development_fold_cannot_touch_holdout(self):
        report = _report()
        report["results"]["SBER"]["walk_forward"]["folds"][1][
            "end_inclusive"
        ] = "2026-11-20"
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("touches or crosses holdout" in e for e in result["errors"]))

    def test_rejects_false_double_cost_survival_claim(self):
        report = _report()
        candidate = report["results"]["SBER"]["adversarial_cost_check"][
            "candidates"
        ]["Donchian20"]
        candidate["survives_double_costs"] = True
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("false double-cost survival" in e for e in result["errors"]))

    def test_rejects_non_doubled_execution_costs(self):
        report = _report()
        report["results"]["SBER"]["adversarial_cost_check"][
            "double_cost_execution_config"
        ]["fee_per_side"] = 0.0015
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")

    def test_missing_ticker_analysis_is_incomplete_not_pass(self):
        report = _report()
        report["results"]["SBER"]["status"] = "DATA_OR_ANALYSIS_ERROR"
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_INCOMPLETE")

    def test_partial_raw_history_coverage_is_reported_as_incomplete(self):
        report = _report()
        audit = report["results"]["SBER"]["session_date_mapping"]
        audit["history_dates_with_raw_fragments"] = 1
        audit["trading_days_reconciled"] = 1
        audit["history_trade_dates_without_raw_fragments"] = 1
        audit["raw_history_date_coverage_ratio"] = 0.5
        audit["raw_history_coverage_status"] = "PARTIAL_DATE_COVERAGE"
        audit["complete"] = False
        audit["status"] = "RECONCILIATION_WITH_CAVEATS"
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_INCOMPLETE")
        self.assertTrue(any("do not fully reconcile" in warning for warning in result["warnings"]))

    def test_inconsistent_raw_history_coverage_is_rejected(self):
        report = _report()
        report["results"]["SBER"]["session_date_mapping"]["raw_history_date_coverage_ratio"] = 0.25
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("coverage ratio is inconsistent" in error for error in result["errors"]))

    def test_inconsistent_price_scale_audit_accounting_is_rejected(self):
        report = _report()
        audit = report["results"]["SBER"]["session_date_mapping"]
        audit["price_scale_mismatch_dates"] = 1
        audit["unexplained_price_scale_mismatch_count"] = 1
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("price-scale factor counts do not sum" in error for error in result["errors"]))

    def test_inconsistent_weekday_additional_session_accounting_is_rejected(self):
        report = _report()
        report["results"]["SBER"]["session_date_mapping"]["raw_weekday_additional_session_candles"] = 1
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("weekday additional-session counts do not sum" in error for error in result["errors"]))

    def test_inconsistent_raw_mapping_reason_totals_are_rejected(self):
        report = _report()
        audit = report["results"]["SBER"]["session_date_mapping"]
        audit["mapped_raw_candles"] = 1
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("mapped and unassigned raw candle counts" in e for e in result["errors"]))

    def test_unassigned_reason_counts_must_sum_to_total(self):
        report = _report()
        report["results"]["SBER"]["session_date_mapping"]["unassigned_reason_counts"] = {
            "WEEKDAY_MISSING_SAME_DATE_HISTORY": 1
        }
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("unassigned reason counts do not sum" in e for e in result["errors"]))

    def test_mismatch_reason_counts_must_sum_to_total(self):
        report = _report()
        report["results"]["SBER"]["session_date_mapping"]["mismatch_reason_counts"] = {
            "AGGREGATED_OHLCV_DIFFERS": 1
        }
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("mismatch reason counts do not sum" in e for e in result["errors"]))

    def test_inconsistent_raw_weekend_fragment_accounting_is_rejected(self):
        report = _report()
        report["results"]["SBER"]["session_date_mapping"]["raw_weekend_candles_mapped"] = 1
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("weekend candle counts do not sum" in error for error in result["errors"]))


    def test_inconsistent_reconciliation_complete_flag_is_rejected(self):
        report = _report()
        report["results"]["SBER"]["session_date_mapping"]["complete"] = False
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("complete flag is inconsistent" in error for error in result["errors"]))

    def test_inconsistent_reconciliation_status_is_rejected(self):
        report = _report()
        report["results"]["SBER"]["session_date_mapping"]["status"] = "RECONCILIATION_WITH_CAVEATS"
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("reconciliation status is inconsistent" in error for error in result["errors"]))

    def test_reconciled_and_mismatched_day_counts_must_cover_grouped_dates(self):
        report = _report()
        report["results"]["SBER"]["session_date_mapping"]["trading_days_reconciled"] = 1
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_FAIL")
        self.assertTrue(any("do not cover raw/history matched dates" in error for error in result["errors"]))

    def test_missing_raw_session_audit_is_incomplete(self):
        report = _report()
        del report["results"]["SBER"]["session_date_mapping"]
        result = validate_research_report(report)
        self.assertEqual(result["status"], "INDEPENDENT_VALIDATION_INCOMPLETE")
        self.assertTrue(any("reconciliation evidence is missing" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
