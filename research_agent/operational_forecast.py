"""Operational inference using a frozen pre-holdout model and current closed Finam D1 bars.

Post-2026-11-20 observations are inference inputs only. Their outcomes are never
used to fit, select, calibrate, or evaluate the model.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .core import Candle, validate_candles
from .direction_forecast import (
    CLASS_NAMES, HOLDOUT_START, HORIZONS, TICKERS,
    build_samples, evaluate_horizon, latest_forecasts,
)


MODEL_VERSION = "gaussian-nb-pre-holdout-v1-2026-11-19"


def _parse_finam_candles(items: list[dict[str, Any]]) -> list[Candle]:
    rows = []
    for item in items:
        if item.get("is_data_snapshot") is True:
            continue
        stamp = datetime.fromisoformat(str(item["timestamp"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("Finam D1 timestamps must be timezone-aware")
        rows.append(Candle(
            stamp,
            float(item["open"]), float(item["high"]), float(item["low"]),
            float(item["close"]), float(item["volume"]),
        ))
    return validate_candles(rows) if rows else []


def build_operational_forecast(
    candles_report: dict[str, Any],
    validation_report: dict[str, Any],
) -> dict[str, Any]:
    """Fit only on labels matured before HOLDOUT_START; infer on latest closed D1 bars."""
    if validation_report.get("status") != "PASS" or validation_report.get("issue_count") != 0:
        raise ValueError("Operational forecast requires a PASS validation report with zero issues")
    if candles_report.get("generated_at_utc") != validation_report.get("generated_at_utc"):
        raise ValueError("Candle and validation snapshots do not match")
    if validation_report.get("generated_at_utc") != validation_report.get("as_of_utc"):
        # The validator normally sets as_of_utc to generated_at_utc. Keep this explicit
        # so a future-dated or manually altered cutoff cannot slip into inference.
        raise ValueError("Validation cutoff must match the collection snapshot time")

    universe = candles_report.get("universe")
    if universe != list(TICKERS):
        raise ValueError("Operational forecast requires the exact frozen 44-symbol universe")
    d1_summary = (candles_report.get("timeframes") or {}).get("D1") or {}
    if (d1_summary.get("symbols") != len(TICKERS)
            or d1_summary.get("ok") != len(TICKERS)
            or d1_summary.get("errors") != 0
            or d1_summary.get("no_completed_bars") != 0):
        raise ValueError("D1 collection must have complete 44/44 Finam coverage")

    candles_by_ticker: dict[str, list[Candle]] = {}
    audits: dict[str, dict[str, Any]] = {}
    data_errors: dict[str, str] = {}
    post_holdout_observations = 0
    dates = []

    results = candles_report.get("results") or {}
    for ticker in TICKERS:
        item = (results.get(ticker) or {}).get("D1") or {}
        if item.get("status") != "OK" or item.get("source") != "Finam":
            candles_by_ticker[ticker] = []
            audits[ticker] = {"status": "ERROR", "error": "Missing native Finam D1 data"}
            data_errors[ticker] = "Missing native Finam D1 data"
            continue
        try:
            rows = _parse_finam_candles(item.get("candles") or [])
            if len(rows) < 60:
                raise ValueError(f"Only {len(rows)} completed D1 bars; at least 60 are required")
            candles_by_ticker[ticker] = rows
            audits[ticker] = {"status": "OK", "bars": len(rows), "source": "Finam"}
            dates.extend(row.timestamp.date() for row in rows)
            post_holdout_observations += sum(
                row.timestamp.date() >= HOLDOUT_START for row in rows
            )
        except Exception as exc:
            candles_by_ticker[ticker] = []
            audits[ticker] = {"status": "ERROR", "error": str(exc)[:500]}
            data_errors[ticker] = str(exc)[:500]

    samples_by_horizon = {
        horizon: [
            sample
            for ticker, rows in candles_by_ticker.items()
            if rows
            for sample in build_samples(ticker, rows, horizon)
        ]
        for horizon in HORIZONS
    }
    # build_samples enforces target_date < HOLDOUT_START. Assert the invariant
    # again at the orchestration boundary before fitting or evaluating.
    for horizon, samples in samples_by_horizon.items():
        if any(sample["date"] >= HOLDOUT_START or sample["target_date"] >= HOLDOUT_START
               for sample in samples):
            raise AssertionError(f"Post-holdout label entered horizon {horizon} training data")

    evaluation = {
        str(horizon): evaluate_horizon(samples_by_horizon[horizon])
        for horizon in HORIZONS
    }
    latest = latest_forecasts(candles_by_ticker, samples_by_horizon)
    as_of_date = latest.get("as_of_date")
    forecasts = []
    for item in latest.get("forecasts", []):
        if not isinstance(item, dict) or "ticker" not in item:
            continue
        row = dict(item)
        row["status"] = "EXPERIMENTAL_NOT_CALIBRATED"
        row["forecast_mode"] = "CURRENT_INFERENCE_ONLY"
        row["model_version"] = MODEL_VERSION
        row["training_label_cutoff_exclusive"] = HOLDOUT_START.isoformat()
        row["post_holdout_outcomes_used"] = False
        probabilities = [
            row.get("probability_down"),
            row.get("probability_sideways"),
            row.get("probability_up"),
        ]
        if (len(probabilities) != 3
                or not all(isinstance(value, (int, float)) and math.isfinite(value)
                           and 0.0 <= value <= 1.0 for value in probabilities)
                or not math.isclose(sum(probabilities), 1.0, rel_tol=0.0, abs_tol=1e-8)):
            raise ValueError(f"Invalid probability vector for {row.get('ticker')} / {row.get('horizon_sessions')}")
        forecasts.append(row)

    expected_keys = {(ticker, horizon) for ticker in TICKERS for horizon in HORIZONS}
    actual_keys = {
        (row["ticker"], row["horizon_sessions"])
        for row in forecasts
    }
    missing = [
        {"ticker": ticker, "horizon_sessions": horizon}
        for ticker, horizon in sorted(expected_keys - actual_keys)
    ]
    current_date = max(dates).isoformat() if dates else None
    return {
        "report_type": "MOEX_EDGE_OPERATIONAL_DIRECTION_FORECAST_V1",
        "status": "COMPLETE" if not data_errors and actual_keys == expected_keys else "PARTIAL",
        "model_version": MODEL_VERSION,
        "calibration_status": "NOT_CALIBRATED",
        "probabilities_are_calibrated": False,
        "model": {
            "name": "Diagonal Gaussian Naive Bayes",
            "classes": list(CLASS_NAMES),
            "horizons_sessions": list(HORIZONS),
            "calibration_status": "NOT_CALIBRATED",
            "probabilities_are_calibrated": False,
            "training_data_cutoff_exclusive": HOLDOUT_START.isoformat(),
        },
        "as_of_date": as_of_date or current_date,
        "generated_at_utc": candles_report.get("generated_at_utc"),
        "universe": list(TICKERS),
        "symbols_with_valid_d1_history": sum(bool(rows) for rows in candles_by_ticker.values()),
        "symbols_with_forecasts": len({row["ticker"] for row in forecasts}),
        "forecast_count": len(forecasts),
        "missing_forecasts": missing,
        "forecasts": forecasts,
        "walk_forward_development_metrics": evaluation,
        "data_audit": audits,
        "data_errors": data_errors,
        "holdout_policy": {
            "holdout_start": HOLDOUT_START.isoformat(),
            "post_holdout_observations_used_as_inference_inputs": post_holdout_observations,
            "post_holdout_outcomes_used_for_training": 0,
            "post_holdout_outcomes_used_for_model_selection": 0,
            "post_holdout_outcomes_used_for_calibration": 0,
            "post_holdout_outcomes_used_for_performance_metrics": 0,
            "training_labels_must_mature_before_holdout": True,
            "inference_parameters_frozen_before_holdout": True,
        },
        "safety": {
            "read_only": True,
            "broker_access": False,
            "orders_or_execution": False,
            "live_trading_authorized": False,
            "probabilities_are_experimental_not_calibrated": True,
            "agents_may_modify_probabilities": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="MOEX EDGE operational forecast from validated closed Finam D1 bars")
    parser.add_argument("--candles", required=True)
    parser.add_argument("--validation", required=True)
    parser.add_argument("--output", default="moex_edge_direction_forecast.json")
    args = parser.parse_args()
    candles = json.loads(Path(args.candles).read_text(encoding="utf-8"))
    validation = json.loads(Path(args.validation).read_text(encoding="utf-8"))
    report = build_operational_forecast(candles, validation)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Operational forecast {report['status']}: "
        f"{report['symbols_with_forecasts']}/{len(TICKERS)} symbols; "
        f"{report['forecast_count']} horizon forecasts; "
        f"post-holdout outcomes used=0; calibration=NOT_CALIBRATED"
    )
    return 0 if report["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
