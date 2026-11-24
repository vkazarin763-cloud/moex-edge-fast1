import unittest

from research_agent.direction_forecast import HORIZONS, TICKERS
from research_agent.integrated_report import build_integrated_report


def _fixtures():
    snapshot = "2026-11-24T18:00:00+00:00"
    latest = {
        ticker: {
            "D1": {"timestamp": "2026-11-23T05:00:00+00:00",
                   "end_utc": "2026-11-23T21:00:00+00:00", "age_minutes": 1260},
            "H1": {"timestamp": "2026-11-24T16:00:00+00:00",
                   "end_utc": "2026-11-24T17:00:00+00:00", "age_minutes": 60},
        }
        for ticker in TICKERS
    }
    candles = {
        "generated_at_utc": snapshot,
        "universe": list(TICKERS),
        "timeframes": {
            "D1": {"symbols": 44, "ok": 44, "errors": 0, "no_completed_bars": 0},
            "H1": {"symbols": 44, "ok": 44, "errors": 0, "no_completed_bars": 0},
        },
    }
    validation = {
        "generated_at_utc": snapshot, "as_of_utc": snapshot,
        "status": "PASS", "issue_count": 0, "latest_closed_bars": latest,
    }
    forecasts = []
    for ticker in TICKERS:
        for horizon in HORIZONS:
            forecasts.append({
                "ticker": ticker, "horizon_sessions": horizon,
                "status": "EXPERIMENTAL_NOT_CALIBRATED",
                "model_version": "frozen-model-test-v1",
                "post_holdout_outcomes_used": False,
                "probability_down": 0.2, "probability_sideways": 0.3,
                "probability_up": 0.5, "predicted_class": "UP",
                "training_samples": 1000,
            })
    forecast = {
        "report_type": "MOEX_EDGE_OPERATIONAL_DIRECTION_FORECAST_V1",
        "status": "COMPLETE", "generated_at_utc": snapshot,
        "universe": list(TICKERS), "model_version": "frozen-model-test-v1",
        "calibration_status": "NOT_CALIBRATED",
        "probabilities_are_calibrated": False, "forecasts": forecasts,
        "holdout_policy": {
            "holdout_start": "2026-11-20",
            "post_holdout_outcomes_used_for_training": 0,
            "post_holdout_outcomes_used_for_model_selection": 0,
            "post_holdout_outcomes_used_for_calibration": 0,
            "post_holdout_outcomes_used_for_performance_metrics": 0,
            "inference_parameters_frozen_before_holdout": True,
        },
    }
    scan = {
        "status": "READ_ONLY_LATEST_SIGNAL_SCAN",
        "generated_at_utc": snapshot, "as_of_utc": snapshot,
        "universe": list(TICKERS), "signals": [],
    }
    agents = {"status": "AGENT_SIGNAL_PROPOSALS", "agent_run_id": "test-run-1", "proposals": []}
    diagnostics = {
        "status": "AGENT_DISCOVERY_COMPLETE", "agent_count": 3,
        "agents_can_modify_probabilities": False,
        "provider": "custom_test_caller", "model": "test-model",
    }
    verification = {
        "status": "AGENT_SIGNAL_VERIFICATION_COMPLETE",
        "agent_run_id": "test-run-1", "deterministic_scan_as_of_utc": snapshot,
        "confirmed_signals_count": 0, "results": [],
    }
    return candles, validation, forecast, scan, agents, diagnostics, verification


def _build(parts):
    return build_integrated_report(*parts)


class IntegratedReportTests(unittest.TestCase):
    def test_builds_44_symbol_report_and_keeps_no_signal_as_valid(self):
        report = _build(_fixtures())
        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(len(report["cards"]), 44)
        self.assertEqual(report["summary"]["forecast_count"], 132)
        self.assertEqual(report["summary"]["state_counts"]["NO_SIGNAL"], 44)
        self.assertEqual(report["summary"]["state_counts"]["CONFIRMED"], 0)
        self.assertEqual(report["summary"]["calibration_status"], "NOT_CALIBRATED")
        self.assertFalse(report["safety"]["live_trading_authorized"])
        self.assertEqual(report["cards"][0]["forecast"]["1"]["predicted_direction"], "UP")

    def test_only_independently_verified_candidate_becomes_confirmed(self):
        parts = list(_fixtures())
        signal = {
            "symbol": "SBER", "direction": "LONG", "strategy": "Donchian20",
            "d1_bar_end_utc": "2026-11-24T21:00:00+00:00",
            "d1_close": 100.0, "h1_confirmation": "CONFIRMED",
            "cross_strategy_conflict": False, "parameters": {},
        }
        proposal = {
            "symbol": "SBER", "direction": "LONG", "strategy": "Donchian20",
            "d1_bar_end_utc": signal["d1_bar_end_utc"],
        }
        verified = {
            **proposal, "status": "CONFIRMED",
            "verified_signal": signal,
        }
        parts[3]["signals"] = [signal]
        parts[4]["proposals"] = [proposal]
        parts[6]["results"] = [verified]
        parts[6]["confirmed_signals_count"] = 1
        report = _build(parts)
        sber = next(card for card in report["cards"] if card["ticker"] == "SBER")
        self.assertEqual(sber["state"], "CONFIRMED")
        self.assertEqual(len(sber["confirmed_signals"]), 1)
        self.assertEqual(report["summary"]["state_counts"]["CONFIRMED"], 1)

    def test_rejects_missing_horizon_or_invalid_probability(self):
        parts = list(_fixtures())
        parts[2]["forecasts"].pop()
        with self.assertRaisesRegex(ValueError, "Missing one or more forecast horizons"):
            _build(parts)
        parts = list(_fixtures())
        parts[2]["forecasts"][0]["probability_up"] = 0.6
        with self.assertRaisesRegex(ValueError, "Invalid probability vector"):
            _build(parts)

    def test_rejects_snapshot_mismatch_and_holdout_policy_violation(self):
        parts = list(_fixtures())
        parts[2]["generated_at_utc"] = "2026-11-25T18:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "snapshots do not match"):
            _build(parts)
        parts = list(_fixtures())
        parts[2]["holdout_policy"]["post_holdout_outcomes_used_for_training"] = 1
        with self.assertRaisesRegex(ValueError, "holdout policy violation"):
            _build(parts)


if __name__ == "__main__":
    unittest.main()
