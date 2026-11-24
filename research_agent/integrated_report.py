"""Assemble validated market, forecast, deterministic scan and AI review into one report.

This module is presentation/orchestration only. It never creates or changes signals,
probabilities, strategy approval, or execution instructions.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .direction_forecast import HORIZONS, TICKERS


REPORT_TYPE = "MOEX_EDGE_INTEGRATED_READ_ONLY_REPORT_V1"
EXPECTED_FORECAST_STATUS = "EXPERIMENTAL_NOT_CALIBRATED"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validate_forecast(report: dict[str, Any], universe: list[str], snapshot_time: str) -> dict[str, dict[int, dict[str, Any]]]:
    _require(report.get("report_type") == "MOEX_EDGE_OPERATIONAL_DIRECTION_FORECAST_V1",
             "Unexpected operational forecast report type")
    _require(report.get("status") == "COMPLETE", "Operational forecast is not complete")
    _require(report.get("generated_at_utc") == snapshot_time,
             "Forecast and market-data snapshots do not match")
    _require(report.get("universe") == universe, "Forecast universe does not match market-data universe")
    _require(report.get("calibration_status") == "NOT_CALIBRATED",
             "Forecast calibration status is missing or unexpected")
    _require(report.get("probabilities_are_calibrated") is False,
             "Forecast must not claim calibrated probabilities")
    policy = report.get("holdout_policy") or {}
    for key in (
        "post_holdout_outcomes_used_for_training",
        "post_holdout_outcomes_used_for_model_selection",
        "post_holdout_outcomes_used_for_calibration",
        "post_holdout_outcomes_used_for_performance_metrics",
    ):
        _require(policy.get(key) == 0, f"Frozen holdout policy violation: {key}")
    _require(policy.get("inference_parameters_frozen_before_holdout") is True,
             "Forecast parameters are not declared frozen before holdout")

    rows = report.get("forecasts")
    _require(isinstance(rows, list), "Forecast rows must be a list")
    by_symbol: dict[str, dict[int, dict[str, Any]]] = {ticker: {} for ticker in universe}
    for row in rows:
        _require(isinstance(row, dict), "Forecast row must be an object")
        ticker, horizon = row.get("ticker"), row.get("horizon_sessions")
        _require(ticker in by_symbol and horizon in HORIZONS,
                 "Forecast row has an unexpected ticker or horizon")
        _require(horizon not in by_symbol[ticker], "Duplicate ticker/horizon forecast")
        _require(row.get("status") == EXPECTED_FORECAST_STATUS,
                 "Forecast row is not marked experimental/not calibrated")
        _require(row.get("post_holdout_outcomes_used") is False,
                 "Forecast row does not attest holdout isolation")
        _require(row.get("model_version") == report.get("model_version"),
                 "Forecast row model version does not match report")
        probabilities = {
            "DOWN": row.get("probability_down"),
            "SIDEWAYS": row.get("probability_sideways"),
            "UP": row.get("probability_up"),
        }
        values = list(probabilities.values())
        _require(
            all(isinstance(value, (int, float)) and math.isfinite(value)
                and 0.0 <= value <= 1.0 for value in values)
            and math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-8),
            f"Invalid probability vector for {ticker}/{horizon}",
        )
        predicted = max(probabilities, key=probabilities.get)
        _require(row.get("predicted_class") == predicted,
                 f"Predicted class does not match maximum probability for {ticker}/{horizon}")
        by_symbol[ticker][horizon] = {
            "horizon_sessions": horizon,
            "probabilities": probabilities,
            "probabilities_percent": {name: value * 100.0 for name, value in probabilities.items()},
            "predicted_direction": predicted,
            "status": EXPECTED_FORECAST_STATUS,
            "training_samples": row.get("training_samples"),
        }
    for ticker in universe:
        _require(set(by_symbol[ticker]) == set(HORIZONS),
                 f"Missing one or more forecast horizons for {ticker}")
    _require(len(rows) == len(universe) * len(HORIZONS),
             "Forecast matrix has an unexpected number of rows")
    return by_symbol


def build_integrated_report(
    candles_report: dict[str, Any],
    validation_report: dict[str, Any],
    forecast_report: dict[str, Any],
    scan_report: dict[str, Any],
    agent_report: dict[str, Any],
    agent_diagnostics: dict[str, Any],
    verification_report: dict[str, Any],
) -> dict[str, Any]:
    """Join validated stage artifacts without changing any upstream decision."""
    _require(validation_report.get("status") == "PASS"
             and validation_report.get("issue_count") == 0,
             "Market-data validation must PASS with zero issues")
    snapshot_time = candles_report.get("generated_at_utc")
    _require(bool(snapshot_time)
             and validation_report.get("generated_at_utc") == snapshot_time
             and validation_report.get("as_of_utc") == snapshot_time,
             "Market data and validation must share one immutable snapshot time")
    universe = candles_report.get("universe")
    _require(universe == list(TICKERS), "Integrated report requires the frozen 44-symbol universe")

    timeframe_summary = candles_report.get("timeframes") or {}
    for frame in ("D1", "H1"):
        coverage = timeframe_summary.get(frame) or {}
        _require(coverage.get("symbols") == len(universe)
                 and coverage.get("ok") == len(universe)
                 and coverage.get("errors") == 0
                 and coverage.get("no_completed_bars") == 0,
                 f"{frame} market-data coverage is incomplete")

    forecasts = _validate_forecast(forecast_report, universe, snapshot_time)
    _require(scan_report.get("status") == "READ_ONLY_LATEST_SIGNAL_SCAN",
             "Deterministic scan has an unexpected status")
    _require(scan_report.get("as_of_utc") == validation_report.get("as_of_utc"),
             "Deterministic scan does not use the validated market-data cutoff")
    _require(scan_report.get("universe") == universe,
             "Deterministic scan universe does not match the market-data universe")
    _require(agent_report.get("status") == "AGENT_SIGNAL_PROPOSALS",
             "Agent proposal report has an unexpected status")
    _require(agent_diagnostics.get("status") == "AGENT_DISCOVERY_COMPLETE",
             "Agent discovery diagnostics are incomplete")
    _require(agent_diagnostics.get("agent_count") == 3,
             "Expected three independent agent roles")
    _require(agent_diagnostics.get("agents_can_modify_probabilities") is False,
             "Agent probability immutability policy is missing")
    _require(verification_report.get("status") == "AGENT_SIGNAL_VERIFICATION_COMPLETE",
             "Independent signal verification is incomplete")
    _require(verification_report.get("deterministic_scan_as_of_utc") == scan_report.get("as_of_utc"),
             "Verification report refers to a different deterministic scan")
    _require(verification_report.get("agent_run_id") == agent_report.get("agent_run_id"),
             "Verification report refers to a different agent run")

    signal_rows = scan_report.get("signals")
    proposal_rows = agent_report.get("proposals")
    verification_rows = verification_report.get("results")
    _require(isinstance(signal_rows, list) and isinstance(proposal_rows, list)
             and isinstance(verification_rows, list),
             "Signals, proposals and verification results must be lists")

    scan_by_symbol: dict[str, list[dict[str, Any]]] = {ticker: [] for ticker in universe}
    for signal in signal_rows:
        _require(signal.get("symbol") in scan_by_symbol, "Scan contains a symbol outside the frozen universe")
        scan_by_symbol[signal["symbol"]].append(signal)

    scan_keys = {
        (row.get("symbol"), row.get("direction"), row.get("strategy"), row.get("d1_bar_end_utc"))
        for row in signal_rows
    }
    verification_by_key = {}
    allowed_verification_states = {
        "CONFIRMED", "VERIFIED_SIGNAL_H1_NOT_CONFIRMED",
        "EXPERIMENTAL_STRATEGY_UNAPPROVED", "REJECTED_NOT_REPRODUCED",
    }
    for result in verification_rows:
        key = (result.get("symbol"), result.get("direction"),
               result.get("strategy"), result.get("d1_bar_end_utc"))
        _require(key not in verification_by_key, "Duplicate agent verification row")
        _require(result.get("status") in allowed_verification_states,
                 "Verification result has an unknown status")
        if result.get("status") == "CONFIRMED":
            verified_signal = result.get("verified_signal")
            _require(key in scan_keys and isinstance(verified_signal, dict)
                     and verified_signal.get("h1_confirmation") == "CONFIRMED",
                     "A confirmed result is not backed by an exact scan row and H1 confirmation")
        verification_by_key[key] = result
    proposal_keys = set()
    for proposal in proposal_rows:
        key = (proposal.get("symbol"), proposal.get("direction"),
               proposal.get("strategy"), proposal.get("d1_bar_end_utc"))
        _require(key not in proposal_keys, "Duplicate consensus proposal")
        _require(key in scan_keys, "Agent proposal is not an exact deterministic scan candidate")
        proposal_keys.add(key)
        _require(key in verification_by_key, "Agent proposal has no independent verification result")

    verified_keys = set(verification_by_key)
    _require(verified_keys == proposal_keys,
             "Verification results do not exactly cover the agent consensus proposals")
    confirmed_count = sum(row.get("status") == "CONFIRMED" for row in verification_rows)
    _require(verification_report.get("confirmed_signals_count") == confirmed_count,
             "Verification confirmed count does not match its result rows")

    cards = []
    state_counts = {"CONFIRMED": 0, "WATCH_OR_UNCONFIRMED": 0, "NO_SIGNAL": 0, "INCOMPLETE": 0}
    for ticker in universe:
        ticker_signals = scan_by_symbol[ticker]
        ticker_verified = [
            verification_by_key[(row["symbol"], row["direction"], row["strategy"], row["d1_bar_end_utc"])]
            for row in ticker_signals
            if (row["symbol"], row["direction"], row["strategy"], row["d1_bar_end_utc"]) in verification_by_key
        ]
        confirmed = [row for row in ticker_verified if row.get("status") == "CONFIRMED"]
        forecasts_for_ticker = forecasts[ticker]
        latest_bars = (validation_report.get("latest_closed_bars") or {}).get(ticker, {})
        d1_bar = latest_bars.get("D1")
        h1_bar = latest_bars.get("H1")

        if not d1_bar or not h1_bar or len(forecasts_for_ticker) != len(HORIZONS):
            state = "INCOMPLETE"
        elif confirmed:
            state = "CONFIRMED"
        elif ticker_signals:
            state = "WATCH_OR_UNCONFIRMED"
        else:
            state = "NO_SIGNAL"
        state_counts[state] += 1

        cards.append({
            "ticker": ticker,
            "state": state,
            "forecast": {
                str(horizon): forecasts_for_ticker[horizon]
                for horizon in HORIZONS
            },
            "deterministic_candidates": ticker_signals,
            "agent_verified_candidates": ticker_verified,
            "confirmed_signals": confirmed,
            "cross_strategy_conflict": any(row.get("cross_strategy_conflict") is True for row in ticker_signals),
            "data_freshness": {
                "d1_latest_closed_bar": d1_bar,
                "h1_latest_closed_bar": h1_bar,
            },
            "interpretation": (
                "A confirmed research candidate passed deterministic reproduction, the strategy research gate and H1 confirmation; this is not a trade instruction."
                if confirmed else
                "One or more deterministic candidates exist, but none passed all independent agent/strategy/H1 gates."
                if ticker_signals else
                "No frozen D1 candidate was produced on the latest completed bar."
            ),
        })

    return {
        "report_type": REPORT_TYPE,
        "status": "COMPLETE",
        "generated_at_utc": snapshot_time,
        "as_of_utc": validation_report.get("as_of_utc"),
        "universe": universe,
        "summary": {
            "symbols": len(universe),
            "state_counts": state_counts,
            "deterministic_candidate_count": len(signal_rows),
            "agent_consensus_proposal_count": len(proposal_rows),
            "independently_confirmed_candidate_count": verification_report.get("confirmed_signals_count", 0),
            "forecast_count": len(forecast_report.get("forecasts", [])),
            "forecast_model_version": forecast_report.get("model_version"),
            "calibration_status": "NOT_CALIBRATED",
            "agent_count": agent_diagnostics.get("agent_count"),
            "ai_provider": agent_diagnostics.get("provider"),
            "ai_model": agent_diagnostics.get("model"),
        },
        "cards": cards,
        "stage_status": {
            "market_data": "PASS",
            "validation": "PASS",
            "forecast": "COMPLETE_EXPERIMENTAL_NOT_CALIBRATED",
            "deterministic_scan": "COMPLETE",
            "agent_discovery": "COMPLETE",
            "independent_verification": "COMPLETE",
        },
        "safety": {
            "read_only": True,
            "broker_access": False,
            "orders_or_execution": False,
            "live_trading_authorized": False,
            "probabilities_are_calibrated": False,
            "agents_can_modify_probabilities": False,
            "no_signal_is_a_valid_outcome": True,
            "frozen_holdout_outcomes_used": 0,
        },
        "limitations": [
            "Forecast probabilities are experimental and not calibrated.",
            "AI-agent consensus is qualitative review, not statistical validation.",
            "Confirmed candidates are research outputs, not trade instructions.",
            "No forecast or candidate implies future profitability.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble MOEX EDGE read-only integrated report")
    for name in ("candles", "validation", "forecast", "scan", "proposals", "diagnostics", "verification"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--output", default="moex_edge_integrated_report.json")
    args = parser.parse_args()
    load = lambda path: json.loads(Path(path).read_text(encoding="utf-8"))
    report = build_integrated_report(
        load(args.candles), load(args.validation), load(args.forecast),
        load(args.scan), load(args.proposals), load(args.diagnostics),
        load(args.verification),
    )
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = report["summary"]["state_counts"]
    print(
        f"Integrated report {report['status']}: {report['summary']['symbols']} symbols; "
        f"confirmed={counts['CONFIRMED']}; watch={counts['WATCH_OR_UNCONFIRMED']}; "
        f"no_signal={counts['NO_SIGNAL']}; incomplete={counts['INCOMPLETE']}; "
        f"forecast_calibration=NOT_CALIBRATED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
