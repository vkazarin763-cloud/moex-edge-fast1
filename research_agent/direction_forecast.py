"""Leakage-safe MOEX direction forecasting research (D1 horizons).

This is a deliberately simple, dependency-free probabilistic baseline. It
compares a diagonal Gaussian Naive Bayes classifier with majority-class and
historical-momentum baselines using expanding chronological folds. It never
reads the frozen holdout.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from statistics import pstdev
from typing import Any

from .core import Candle, _ema, _wilder_atr, _wilder_rsi, validate_candles
from .candle_level_research import (
    DATA_START, HOLDOUT_START, TICKERS, _fetch_d1_model_rows,
)

CLASS_NAMES = ("DOWN", "SIDEWAYS", "UP")
CLASS_DOWN, CLASS_SIDEWAYS, CLASS_UP = 0, 1, 2
HORIZONS = (1, 5, 20)
ROUND_TRIP_COST = 0.003
MIN_TRAIN_SAMPLES = 100
MIN_TEST_SAMPLES = 20
FEATURE_NAMES = (
    "return_1", "return_3", "return_5", "return_10", "return_20",
    "ema20_ema50_spread", "ema20_slope_5", "rsi14_centered",
    "atr14_pct", "prior20_range_position", "relative_volume_20",
    "realized_volatility_20", "candle_body_fraction",
    "wick_imbalance", "distance_prior20_high", "distance_prior20_low",
)


def _feature_vector(rows: list[Candle], index: int) -> list[float] | None:
    if index < 55 or index >= len(rows):
        return None
    closes = [row.close for row in rows]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    rsi = _wilder_rsi(closes, 14)
    atr = _wilder_atr(rows, 14)
    return _feature_from_indicators(rows, index, ema20, ema50, rsi, atr)


def _feature_arrays(rows: list[Candle]):
    closes = [row.close for row in rows]
    return _ema(closes, 20), _ema(closes, 50), _wilder_rsi(closes, 14), _wilder_atr(rows, 14)


def _feature_from_indicators(rows, index, ema20, ema50, rsi, atr):
    current = rows[index]
    close = current.close
    if close <= 0 or rsi[index] is None or atr[index] is None:
        return None
    prior = rows[index - 20:index]
    if len(prior) != 20:
        return None
    prior_high = max(row.high for row in prior)
    prior_low = min(row.low for row in prior)
    prior_range = prior_high - prior_low
    avg_volume = sum(row.volume for row in prior) / len(prior)
    if prior_range <= 0 or avg_volume <= 0:
        return None
    prior_returns = [
        rows[j].close / rows[j - 1].close - 1.0
        for j in range(index - 19, index)
        if rows[j - 1].close > 0
    ]
    if len(prior_returns) < 10:
        return None
    candle_range = current.high - current.low
    if candle_range <= 0:
        return None
    body = current.close - current.open
    lower_wick = min(current.open, current.close) - current.low
    upper_wick = current.high - max(current.open, current.close)
    values = [
        close / rows[index - 1].close - 1.0,
        close / rows[index - 3].close - 1.0,
        close / rows[index - 5].close - 1.0,
        close / rows[index - 10].close - 1.0,
        close / rows[index - 20].close - 1.0,
        (ema20[index] - ema50[index]) / close,
        (ema20[index] - ema20[index - 5]) / close,
        (rsi[index] - 50.0) / 50.0,
        atr[index] / close,
        (close - prior_low) / prior_range,
        math.log(max(current.volume, 1.0) / avg_volume),
        pstdev(prior_returns),
        body / candle_range,
        (lower_wick - upper_wick) / candle_range,
        close / prior_high - 1.0,
        close / prior_low - 1.0,
    ]
    if len(values) != len(FEATURE_NAMES) or not all(math.isfinite(value) for value in values):
        return None
    return values


def build_samples(
    ticker: str,
    candles: list[Candle],
    horizon: int,
) -> list[dict[str, Any]]:
    """Build point-in-time features and future labels; target must remain pre-holdout."""
    if horizon not in HORIZONS:
        raise ValueError(f"Unsupported horizon: {horizon}")
    rows = validate_candles(candles)
    ema20, ema50, rsi, atr = _feature_arrays(rows)
    samples = []
    for index in range(55, len(rows) - horizon):
        features = _feature_from_indicators(rows, index, ema20, ema50, rsi, atr)
        if features is None:
            continue
        target_index = index + horizon
        target_date = rows[target_index].timestamp.date()
        if target_date >= HOLDOUT_START:
            continue
        current_close = rows[index].close
        future_return = rows[target_index].close / current_close - 1.0
        atr_pct = atr[index] / current_close
        neutral_threshold = max(ROUND_TRIP_COST, 0.5 * atr_pct * math.sqrt(horizon))
        if future_return > neutral_threshold:
            label = CLASS_UP
        elif future_return < -neutral_threshold:
            label = CLASS_DOWN
        else:
            label = CLASS_SIDEWAYS
        samples.append({
            "ticker": ticker,
            "date": rows[index].timestamp.date(),
            "target_date": target_date,
            "features": features,
            "label": label,
            "future_return": future_return,
            "neutral_threshold": neutral_threshold,
        })
    return samples


def _fit_gaussian_nb(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if len(samples) < MIN_TRAIN_SAMPLES:
        raise ValueError("Insufficient training samples")
    width = len(FEATURE_NAMES)
    matrix = [sample["features"] for sample in samples]
    global_mean = [
        sum(row[j] for row in matrix) / len(matrix)
        for j in range(width)
    ]
    global_std = []
    for j in range(width):
        variance = sum((row[j] - global_mean[j]) ** 2 for row in matrix) / len(matrix)
        global_std.append(max(math.sqrt(variance), 1e-8))
    scaled = [
        [(row[j] - global_mean[j]) / global_std[j] for j in range(width)]
        for row in matrix
    ]
    labels = [sample["label"] for sample in samples]
    counts = Counter(labels)
    model = {
        "global_mean": global_mean,
        "global_std": global_std,
        "priors": [],
        "means": [],
        "variances": [],
        "train_count": len(samples),
        "class_counts": {CLASS_NAMES[key]: counts.get(key, 0) for key in range(3)},
    }
    for label in range(3):
        selected = [scaled[i] for i, value in enumerate(labels) if value == label]
        count = len(selected)
        model["priors"].append((count + 1.0) / (len(samples) + 3.0))
        if not selected:
            model["means"].append([0.0] * width)
            model["variances"].append([1.0] * width)
            continue
        means = [
            sum(row[j] for row in selected) / count
            for j in range(width)
        ]
        variances = []
        for j in range(width):
            variance = sum((row[j] - means[j]) ** 2 for row in selected) / count
            variances.append(max(variance, 1e-3))
        model["means"].append(means)
        model["variances"].append(variances)
    return model


def _predict_proba(model: dict[str, Any], features: list[float]) -> list[float]:
    width = len(FEATURE_NAMES)
    scaled = [
        (features[j] - model["global_mean"][j]) / model["global_std"][j]
        for j in range(width)
    ]
    log_probabilities = []
    for label in range(3):
        score = math.log(model["priors"][label])
        for j in range(width):
            variance = model["variances"][label][j]
            delta = scaled[j] - model["means"][label][j]
            score -= 0.5 * (math.log(2.0 * math.pi * variance) + delta * delta / variance)
        log_probabilities.append(score)
    maximum = max(log_probabilities)
    exp_values = [math.exp(value - maximum) for value in log_probabilities]
    total = sum(exp_values)
    return [value / total for value in exp_values]


def _metrics(
    predictions: list[tuple[int, list[float], int, int]],
    train_counts: dict[str, int],
) -> dict[str, Any]:
    if not predictions:
        return {"status": "INSUFFICIENT_TEST_DATA", "test_samples": 0}
    actual = [item[0] for item in predictions]
    probabilities = [item[1] for item in predictions]
    model_labels = [max(range(3), key=lambda label: probs[label]) for probs in probabilities]
    momentum_labels = [item[2] for item in predictions]
    momentum_accuracy = sum(a == b for a, b in zip(actual, momentum_labels)) / len(actual)
    accuracy = sum(a == b for a, b in zip(actual, model_labels)) / len(actual)
    recalls = []
    for label in range(3):
        indexes = [i for i, value in enumerate(actual) if value == label]
        if indexes:
            recalls.append(sum(model_labels[i] == label for i in indexes) / len(indexes))
    log_loss = -sum(
        math.log(max(probabilities[i][actual[i]], 1e-15))
        for i in range(len(actual))
    ) / len(actual)
    brier = sum(
        sum((probabilities[i][label] - (1.0 if actual[i] == label else 0.0)) ** 2 for label in range(3))
        for i in range(len(actual))
    ) / len(actual)
    average_probabilities = [
        sum(probs[label] for probs in probabilities) / len(probabilities)
        for label in range(3)
    ]
    return {
        "status": "EVALUATED",
        "test_samples": len(actual),
        "accuracy": accuracy,
        "balanced_accuracy": sum(recalls) / len(recalls) if recalls else None,
        "log_loss": log_loss,
        "multiclass_brier_score": brier,
        "majority_baseline_accuracy": majority_accuracy,
        "historical_momentum_baseline_accuracy": momentum_accuracy,
        "actual_class_counts": {CLASS_NAMES[label]: actual.count(label) for label in range(3)},
        "average_predicted_probabilities": {
            CLASS_NAMES[label]: average_probabilities[label] for label in range(3)
        },
    }


def evaluate_horizon(
    samples: list[dict[str, Any]],
    *,
    folds: int = 4,
    initial_train_fraction: float = 0.5,
) -> dict[str, Any]:
    """Expanding-window evaluation with label-maturity embargo at every fold boundary."""
    dates = sorted({sample["date"] for sample in samples})
    if len(dates) < 30 or folds < 2 or not 0.3 <= initial_train_fraction < 0.8:
        return {"status": "INSUFFICIENT_HISTORY", "samples": len(samples)}
    first_test = max(1, int(len(dates) * initial_train_fraction))
    remaining = len(dates) - first_test
    fold_size = remaining // folds
    if fold_size < 5:
        return {"status": "INSUFFICIENT_HISTORY", "samples": len(samples)}
    out_of_sample = []
    fold_reports = []
    for fold in range(folds):
        start_index = first_test + fold * fold_size
        end_index = first_test + (fold + 1) * fold_size if fold < folds - 1 else len(dates)
        test_start = dates[start_index]
        test_end = dates[end_index] if end_index < len(dates) else dates[-1] + timedelta(days=1)
        training = [
            sample for sample in samples
            if sample["date"] < test_start and sample["target_date"] < test_start
        ]
        testing = [
            sample for sample in samples
            if test_start <= sample["date"] < test_end and sample["target_date"] < test_end
        ]
        if len(training) < MIN_TRAIN_SAMPLES or len(testing) < MIN_TEST_SAMPLES:
            fold_reports.append({
                "fold": fold + 1, "status": "INSUFFICIENT_FOLD_DATA",
                "train_samples": len(training), "test_samples": len(testing),
            })
            continue
        model = _fit_gaussian_nb(training)
        predictions = []
        for sample in testing:
            probabilities = _predict_proba(model, sample["features"])
            momentum_return = sample["features"][2]
            if momentum_return > sample["neutral_threshold"]:
                momentum_label = CLASS_UP
            elif momentum_return < -sample["neutral_threshold"]:
                momentum_label = CLASS_DOWN
            else:
                momentum_label = CLASS_SIDEWAYS
            majority_label = max(
                range(3),
                key=lambda label: model["class_counts"].get(CLASS_NAMES[label], 0),
            )
            predictions.append((sample["label"], probabilities, momentum_label, majority_label))
        metrics = _metrics(predictions, model["class_counts"])
        fold_reports.append({
            "fold": fold + 1,
            "status": "EVALUATED",
            "test_start": test_start.isoformat(),
            "test_end_exclusive": test_end.isoformat(),
            "train_samples": len(training),
            "train_max_label_maturity_date": max(sample["target_date"] for sample in training).isoformat(),
            "metrics": metrics,
        })
        out_of_sample.extend(predictions)
    if not out_of_sample:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "samples": len(samples),
            "folds": fold_reports,
        }
    # Aggregate metrics from the pooled out-of-sample predictions.
    pooled = _metrics(out_of_sample, {})
    pooled["status"] = "OUT_OF_SAMPLE_EVALUATED"
    return {
        "status": "OUT_OF_SAMPLE_EVALUATED",
        "samples": len(samples),
        "oos_samples": len(out_of_sample),
        "folds_requested": folds,
        "folds_evaluated": sum(item["status"] == "EVALUATED" for item in fold_reports),
        "fold_reports": fold_reports,
        "pooled_oos_metrics": pooled,
        "validation_policy": (
            "Expanding chronological folds; training labels must mature before each test start; "
            "test labels must mature before the test-fold end. No random split."
        ),
    }


def latest_forecasts(
    candles_by_ticker: dict[str, list[Candle]],
    samples_by_horizon: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Generate historical as-of forecasts using only labels matured before the as-of date."""
    latest_dates = [
        rows[-1].timestamp.date()
        for rows in candles_by_ticker.values() if rows
    ]
    if not latest_dates:
        return {"status": "NO_DATA", "forecasts": []}
    as_of = max(latest_dates)
    forecasts = []
    for horizon in HORIZONS:
        training = [
            sample for sample in samples_by_horizon[horizon]
            if sample["target_date"] < as_of
        ]
        if len(training) < MIN_TRAIN_SAMPLES:
            forecasts.append({
                "horizon_sessions": horizon,
                "status": "INSUFFICIENT_TRAINING_HISTORY",
                "training_samples": len(training),
            })
            continue
        model = _fit_gaussian_nb(training)
        for ticker, rows in sorted(candles_by_ticker.items()):
            if not rows:
                continue
            latest = rows[-1]
            age_days = (as_of - latest.timestamp.date()).days
            if age_days > 5 or len(rows) < 60:
                continue
            ema20, ema50, rsi, atr = _feature_arrays(rows)
            features = _feature_from_indicators(rows, len(rows) - 1, ema20, ema50, rsi, atr)
            if features is None:
                continue
            probabilities = _predict_proba(model, features)
            forecasts.append({
                "ticker": ticker,
                "as_of_date": latest.timestamp.date().isoformat(),
                "horizon_sessions": horizon,
                "status": "HISTORICAL_FORECAST_ONLY",
                "probability_down": probabilities[CLASS_DOWN],
                "probability_sideways": probabilities[CLASS_SIDEWAYS],
                "probability_up": probabilities[CLASS_UP],
                "predicted_class": CLASS_NAMES[max(range(3), key=lambda label: probabilities[label])],
                "training_samples": len(training),
                "training_class_counts": model["class_counts"],
            })
    return {
        "status": "HISTORICAL_FORECASTS_ONLY",
        "as_of_date": as_of.isoformat(),
        "forecasts": forecasts,
        "usage": (
            "Historical as-of forecasts only. The as-of date is before the frozen holdout; "
            "these are not current live signals and must not be used as trade instructions."
        ),
    }


def run_direction_forecast() -> dict[str, Any]:
    start_text = DATA_START.isoformat()
    end_text = (HOLDOUT_START - timedelta(days=1)).isoformat()
    candles_by_ticker: dict[str, list[Candle]] = {}
    audits: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for ticker in TICKERS:
        try:
            rows, audit = _fetch_d1_model_rows(ticker, start_text, end_text)
            if rows:
                candles_by_ticker[ticker] = validate_candles(rows)
            else:
                candles_by_ticker[ticker] = []
            audits[ticker] = audit
        except Exception as exc:
            candles_by_ticker[ticker] = []
            errors[ticker] = str(exc)[:500]
            audits[ticker] = {"status": "ERROR", "error": str(exc)[:500]}
    samples_by_horizon = {
        horizon: [
            sample
            for ticker, rows in candles_by_ticker.items()
            if rows
            for sample in build_samples(ticker, rows, horizon)
        ]
        for horizon in HORIZONS
    }
    evaluation = {
        str(horizon): evaluate_horizon(samples_by_horizon[horizon])
        for horizon in HORIZONS
    }
    forecast = latest_forecasts(candles_by_ticker, samples_by_horizon)
    available = sum(bool(rows) for rows in candles_by_ticker.values())
    return {
        "report_type": "MOEX_DIRECTION_FORECAST_RESEARCH_V1",
        "status": "COMPLETE" if available == len(TICKERS) and not errors else "PARTIAL",
        "generated_scope": "DEVELOPMENT_ONLY_NO_HOLDOUT",
        "source": "MOEX ISS TQBR total-session D1 history with corporate-action price-basis exclusions",
        "universe": list(TICKERS),
        "universe_size": len(TICKERS),
        "symbols_with_eligible_history": available,
        "symbols_without_eligible_history": len(TICKERS) - available,
        "date_from": start_text,
        "date_till_exclusive": HOLDOUT_START.isoformat(),
        "holdout_start": HOLDOUT_START.isoformat(),
        "holdout_bars_used": 0,
        "data_audit": audits,
        "data_errors": errors,
        "model": {
            "name": "Diagonal Gaussian Naive Bayes",
            "purpose": "Simple three-class probability baseline; not a live trading model.",
            "features": list(FEATURE_NAMES),
            "classes": list(CLASS_NAMES),
            "horizons_sessions": list(HORIZONS),
            "neutral_zone": (
                "max(0.30% assumed round-trip cost, 0.5 x ATR14/close x sqrt(horizon)); "
                "UP/DOWN labels require returns outside this neutral zone."
            ),
            "assumed_round_trip_cost": ROUND_TRIP_COST,
            "dependencies": "Python standard library only",
            "limitations": [
                "Diagonal Gaussian assumptions ignore feature dependence.",
                "Probabilities are uncalibrated until calibration is assessed on separate data.",
                "D1 horizons only; H1 history is not long enough for this historical model.",
            ],
        },
        "walk_forward": evaluation,
        "historical_latest_forecasts": forecast,
        "safety": {
            "read_only": True,
            "broker_access": False,
            "orders_or_execution": False,
            "live_trading_authorized": False,
            "holdout_used_for_training_or_selection": False,
            "latest_forecasts_are_current": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Leakage-safe MOEX D1 direction forecast research")
    parser.add_argument("--output", default="moex_direction_forecast_report.json")
    args = parser.parse_args()
    report = run_direction_forecast()
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Direction forecast research {report['status']}: "
        f"{report['symbols_with_eligible_history']}/{report['universe_size']} symbols; "
        f"holdout bars used={report['holdout_bars_used']}"
    )
    return 0 if report["symbols_with_eligible_history"] > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
