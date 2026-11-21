"""Chronological walk-forward evaluation and conservative candidate gating."""
from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from .core import BacktestConfig, Candle, backtest, generate_signals, summarize, validate_candles


def _execution_config(config: BacktestConfig) -> dict[str, Any]:
    """Serialize the exact simulator assumptions used by a research report."""
    return {
        "fee_per_side": config.fee_per_side,
        "slippage_per_side": config.slippage_per_side,
        "stop_pct": config.stop_pct,
        "target_pct": config.target_pct,
        "max_bars": config.max_bars,
    }


def walk_forward_report(candles: list[Candle], folds: int = 4, warmup_bars: int = 200,
                        min_total_trades: int = 30, min_trades_per_fold: int = 5,
                        config: BacktestConfig = BacktestConfig()) -> dict[str, Any]:
    """Evaluate fixed, pre-registered strategies on sequential unseen time windows.

    Each fold uses only candles up to that fold's end. Earlier candles are indicator
    warm-up only; only signals inside the fold are evaluated. Open positions at a
    fold boundary are excluded from realized metrics, never force-closed.
    """
    rows = validate_candles(candles)
    if folds < 2:
        raise ValueError("folds must be at least 2")
    if warmup_bars < 55:
        raise ValueError("warmup_bars must be >= 55 for current signal definitions")
    if min_total_trades < 1 or min_trades_per_fold < 0:
        raise ValueError("trade thresholds are invalid")
    available = len(rows) - warmup_bars
    if available < folds * 2:
        raise ValueError("Not enough candles for requested folds and warm-up")
    fold_size = available // folds
    fold_reports = []
    all_by_strategy: dict[str, list] = {}
    all_by_direction_strategy: dict[str, dict[str, list]] = {"LONG": {}, "SHORT": {}}

    for fold in range(folds):
        start = warmup_bars + fold * fold_size
        end = warmup_bars + (fold + 1) * fold_size if fold < folds - 1 else len(rows)
        history = rows[:end]
        signals = [s for s in generate_signals(history)
                   if start <= s.index < end - 1]
        trades = backtest(history, signals, config)
        strategies = sorted({s.strategy for s in signals} | {t.strategy for t in trades})
        per_strategy = {}
        for strategy in strategies:
            selected = [t for t in trades if t.strategy == strategy]
            stats = summarize(selected)
            per_strategy[strategy] = stats
            all_by_strategy.setdefault(strategy, []).extend(selected)
        per_direction = {}
        for direction, direction_name in ((1, "LONG"), (-1, "SHORT")):
            direction_stats = {}
            for strategy in strategies:
                selected = [
                    trade for trade in trades
                    if trade.strategy == strategy and trade.direction == direction
                ]
                direction_stats[strategy] = summarize(selected)
                all_by_direction_strategy[direction_name].setdefault(strategy, []).extend(selected)
            per_direction[direction_name] = direction_stats
        trade_ledger = [
            {
                "strategy": trade.strategy,
                "direction": "LONG" if trade.direction == 1 else "SHORT",
                "signal_time": trade.signal_time.isoformat(),
                "entry_time": trade.entry_time.isoformat(),
                "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "net_return": trade.net_return,
                "status": trade.status,
                "exit_reason": trade.exit_reason,
            }
            for trade in trades
        ]
        fold_reports.append({
            "fold": fold + 1,
            "start": rows[start].timestamp.isoformat(),
            "end_inclusive": rows[end - 1].timestamp.isoformat(),
            "strategies": per_strategy,
            "by_direction": per_direction,
            "trade_ledger": trade_ledger,
        })

    candidates = {}
    for strategy, trades in sorted(all_by_strategy.items()):
        stats = summarize(trades)
        fold_stats = [f["strategies"].get(strategy, summarize([])) for f in fold_reports]
        positive_folds = sum(
            (s["average_net_return"] is not None and s["average_net_return"] > 0)
            for s in fold_stats
        )
        adequately_sampled_folds = sum(
            s["closed_trades"] >= min_trades_per_fold for s in fold_stats
        )
        # A candidate is only "promising" for further manual review, never production-ready.
        passes = (
            stats["closed_trades"] >= min_total_trades
            and adequately_sampled_folds == folds
            and positive_folds >= math.ceil(0.75 * folds)
            and stats["average_net_return"] is not None
            and stats["average_net_return"] > 0
            and (
                stats["profit_factor_infinite"]
                or (stats["profit_factor"] is not None and stats["profit_factor"] > 1.0)
            )
        )
        candidates[strategy] = {
            **stats,
            "positive_folds": positive_folds,
            "adequately_sampled_folds": adequately_sampled_folds,
            "folds": folds,
            "status": "DEVELOPMENT_SCREEN_PASS_UNADJUSTED" if passes else "REJECT_OR_INSUFFICIENT_EVIDENCE",
        }

    candidates_by_direction = {}
    for direction_name, strategy_groups in all_by_direction_strategy.items():
        candidates_by_direction[direction_name] = {}
        for strategy, direction_trades in sorted(strategy_groups.items()):
            stats = summarize(direction_trades)
            fold_stats = [
                fold["by_direction"][direction_name].get(strategy, summarize([]))
                for fold in fold_reports
            ]
            positive_folds = sum(
                item["average_net_return"] is not None and item["average_net_return"] > 0
                for item in fold_stats
            )
            adequately_sampled_folds = sum(
                item["closed_trades"] >= min_trades_per_fold for item in fold_stats
            )
            passes = (
                stats["closed_trades"] >= min_total_trades
                and adequately_sampled_folds == folds
                and positive_folds >= math.ceil(0.75 * folds)
                and stats["average_net_return"] is not None
                and stats["average_net_return"] > 0
                and (
                    stats["profit_factor_infinite"]
                    or (stats["profit_factor"] is not None and stats["profit_factor"] > 1.0)
                )
            )
            candidates_by_direction[direction_name][strategy] = {
                **stats,
                "positive_folds": positive_folds,
                "adequately_sampled_folds": adequately_sampled_folds,
                "folds": folds,
                "status": "DEVELOPMENT_SCREEN_PASS_UNADJUSTED" if passes else "REJECT_OR_INSUFFICIENT_EVIDENCE",
            }
    return {
        "method": "expanding-history indicators; sequential non-overlapping test folds; fixed candidates",
        "candles": len(rows),
        "execution_config": _execution_config(config),
        "warmup_bars": warmup_bars,
        "folds": fold_reports,
        "candidates": candidates,
        "by_direction": candidates_by_direction,
        "direction_scope": "LONG and SHORT are separate diagnostic replays within each fold; they are not additive portfolio attribution and do not apply a cross-direction position cap.",
        "trade_ledger_scope": "The fold trade ledger records the exact simulated signal, next-bar entry, exit, net return, status, and exit reason for auditability. It is descriptive research output only and does not alter candidate selection or portfolio attribution.",
        "warning": "Development screening only. Candidate pass labels are unadjusted for multiple testing and are not independent validation, profitability evidence, or production approval.",
    }



def cross_sectional_direction_summary(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Summarize per-ticker directional walk-forward diagnostics across a universe.

    This is a descriptive cross-sectional aggregation, not a portfolio simulation:
    ticker returns are never added together and no shared position cap is applied.
    """
    summary: dict[str, Any] = {
        "scope": (
            "Cross-sectional summary of per-ticker walk-forward diagnostics. "
            "Not a portfolio return; ticker returns are not compounded or added, "
            "and no shared-capacity constraint is applied."
        ),
        "by_direction": {},
    }
    for direction in ("LONG", "SHORT"):
        summary["by_direction"][direction] = {}
        for strategy in (
            "Donchian20", "EMA20x50", "Keltner20x2ATR",
            "MACD12x26", "RSI14Trend50",
        ):
            ticker_averages = []
            total_trades = 0
            weighted_return_sum = 0.0
            positive_tickers = 0
            adequately_sampled_tickers = 0
            positive_ticker_folds = 0
            ticker_folds_with_trades = 0
            for ticker_result in results.values():
                if not isinstance(ticker_result, dict) or ticker_result.get("status") != "ANALYZED":
                    continue
                walk = ticker_result.get("walk_forward") or {}
                candidate = (walk.get("by_direction") or {}).get(direction, {}).get(strategy)
                if not isinstance(candidate, dict):
                    continue
                trades = int(candidate.get("closed_trades") or 0)
                average = candidate.get("average_net_return")
                if trades > 0 and average is not None:
                    ticker_averages.append(float(average))
                    total_trades += trades
                    weighted_return_sum += float(average) * trades
                    positive_tickers += int(float(average) > 0)
                    adequately_sampled_tickers += int(
                        trades >= 30
                        and candidate.get("adequately_sampled_folds") == candidate.get("folds")
                    )
                for fold in walk.get("folds", []):
                    fold_stats = (
                        (fold.get("by_direction") or {})
                        .get(direction, {})
                        .get(strategy, {})
                    )
                    fold_trades = int(fold_stats.get("closed_trades") or 0)
                    fold_average = fold_stats.get("average_net_return")
                    if fold_trades > 0 and fold_average is not None:
                        ticker_folds_with_trades += 1
                        positive_ticker_folds += int(float(fold_average) > 0)
            ticker_count = len(ticker_averages)
            summary["by_direction"][direction][strategy] = {
                "tickers_with_closed_trades": ticker_count,
                "total_closed_trades": total_trades,
                "trade_weighted_average_net_return": (
                    weighted_return_sum / total_trades if total_trades else None
                ),
                "equal_weight_mean_ticker_average_net_return": (
                    sum(ticker_averages) / ticker_count if ticker_count else None
                ),
                "median_ticker_average_net_return": (
                    sorted(ticker_averages)[ticker_count // 2]
                    if ticker_count % 2 == 1 else (
                        (sorted(ticker_averages)[ticker_count // 2 - 1]
                         + sorted(ticker_averages)[ticker_count // 2]) / 2
                        if ticker_count else None
                    )
                ),
                "positive_tickers": positive_tickers,
                "positive_ticker_share": (
                    positive_tickers / ticker_count if ticker_count else None
                ),
                "tickers_with_30plus_trades_and_all_folds_adequate": adequately_sampled_tickers,
                "positive_ticker_folds": positive_ticker_folds,
                "ticker_folds_with_trades": ticker_folds_with_trades,
                "positive_ticker_fold_share": (
                    positive_ticker_folds / ticker_folds_with_trades
                    if ticker_folds_with_trades else None
                ),
            }
    return summary

def adversarial_cost_check(candles: list[Candle], folds: int = 4,
                           warmup_bars: int = 200,
                           min_total_trades: int = 30,
                           min_trades_per_fold: int = 5,
                           config: BacktestConfig = BacktestConfig(),
                           baseline_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Re-run the same fixed hypotheses with doubled fees and slippage.

    A matching baseline report may be supplied by callers that have already
    computed it. This avoids repeating the identical baseline walk-forward run;
    the stressed run is always recalculated with doubled costs.
    """
    expected_config = _execution_config(config)
    if baseline_report is None:
        baseline = walk_forward_report(
            candles, folds, warmup_bars, min_total_trades, min_trades_per_fold, config
        )
    else:
        if (not isinstance(baseline_report, dict)
                or baseline_report.get("execution_config") != expected_config
                or not isinstance(baseline_report.get("candidates"), dict)):
            raise ValueError("baseline_report must match the supplied execution config")
        baseline = baseline_report
    stressed_config = replace(
        config,
        fee_per_side=config.fee_per_side * 2.0,
        slippage_per_side=config.slippage_per_side * 2.0,
    )
    stressed = walk_forward_report(
        candles, folds, warmup_bars, min_total_trades, min_trades_per_fold,
        stressed_config,
    )
    results = {}
    for strategy, base in baseline["candidates"].items():
        stress = stressed["candidates"].get(strategy)
        survives = bool(
            base["status"] == "DEVELOPMENT_SCREEN_PASS_UNADJUSTED"
            and stress
            and stress["status"] == "DEVELOPMENT_SCREEN_PASS_UNADJUSTED"
            and stress["average_net_return"] is not None
            and stress["average_net_return"] > 0
        )
        results[strategy] = {
            "baseline_status": base["status"],
            "double_cost_status": stress["status"] if stress else "NO_STRESS_SAMPLE",
            "survives_double_costs": survives,
            "baseline_average_net_return": base["average_net_return"],
            "double_cost_average_net_return": stress["average_net_return"] if stress else None,
            "by_direction": {},
        }
        for direction_name, direction_candidates in baseline.get("by_direction", {}).items():
            direction_base = direction_candidates.get(strategy)
            direction_stress = stressed.get("by_direction", {}).get(direction_name, {}).get(strategy)
            direction_survives = bool(
                direction_base
                and direction_base["status"] == "DEVELOPMENT_SCREEN_PASS_UNADJUSTED"
                and direction_stress
                and direction_stress["status"] == "DEVELOPMENT_SCREEN_PASS_UNADJUSTED"
                and direction_stress["average_net_return"] is not None
                and direction_stress["average_net_return"] > 0
            )
            results[strategy]["by_direction"][direction_name] = {
                "baseline_status": direction_base["status"] if direction_base else "NO_BASELINE_SAMPLE",
                "double_cost_status": direction_stress["status"] if direction_stress else "NO_STRESS_SAMPLE",
                "survives_double_costs": direction_survives,
                "baseline_average_net_return": direction_base["average_net_return"] if direction_base else None,
                "double_cost_average_net_return": direction_stress["average_net_return"] if direction_stress else None,
            }
    return {
        "stress": "2x entry/exit fees and slippage",
        "baseline_execution_config": _execution_config(config),
        "double_cost_execution_config": _execution_config(stressed_config),
        "candidates": results,
        "warning": "Cost sensitivity only; it does not replace a separate holdout dataset or independent review.",
    }


# The candidate list and cutoff are frozen before any prospective observations.
CANDIDATE_SET_VERSION = "v1-frozen-2026-11-19"
REGISTERED_CANDIDATES = (
    "Donchian20", "EMA20x50", "RSI14Trend50", "MACD12x26", "Keltner20x2ATR",
)


def _newey_west_mean_test(values: list[float]) -> dict[str, Any]:
    """One-sided HAC test of positive mean trade return with Bartlett weights."""
    n = len(values)
    if n < 5:
        return {"pvalue": None, "z_statistic": None, "lags": None}
    mean = sum(values) / n
    residuals = [value - mean for value in values]
    max_lag = min(n - 1, max(1, int(math.floor(math.sqrt(n)))))
    long_run_variance = sum(value * value for value in residuals) / n
    for lag in range(1, max_lag + 1):
        covariance = sum(
            residuals[index] * residuals[index - lag]
            for index in range(lag, n)
        ) / n
        weight = 1.0 - lag / (max_lag + 1.0)
        long_run_variance += 2.0 * weight * covariance
    if not math.isfinite(long_run_variance) or long_run_variance <= 0:
        return {"pvalue": 1.0, "z_statistic": None, "lags": max_lag}
    standard_error = math.sqrt(long_run_variance / n)
    z_statistic = mean / standard_error
    pvalue = 0.5 * math.erfc(z_statistic / math.sqrt(2.0))
    return {"pvalue": min(1.0, max(0.0, pvalue)),
            "z_statistic": z_statistic, "lags": max_lag}


def _block_bootstrap_mean_ci(
    values: list[float], samples: int = 1000, confidence: float = 0.95, seed: int = 0,
) -> dict[str, Any] | None:
    """Moving-block bootstrap CI; contiguous trade blocks retain local dependence."""
    import random

    n = len(values)
    if n < 5:
        return None
    block = max(1, int(round(math.sqrt(n))))
    rng = random.Random(seed)
    means = []
    for _ in range(samples):
        sample = []
        while len(sample) < n:
            start = rng.randrange(0, n - block + 1)
            sample.extend(values[start:start + block])
        sample = sample[:n]
        means.append(sum(sample) / n)
    means.sort()

    def quantile(q: float) -> float:
        position = (len(means) - 1) * q
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return means[lower]
        fraction = position - lower
        return means[lower] * (1.0 - fraction) + means[upper] * fraction

    alpha = (1.0 - confidence) / 2.0
    return {
        "lower": quantile(alpha),
        "upper": quantile(1.0 - alpha),
        "confidence": confidence,
        "method": "moving_block_bootstrap_percentile",
        "block_length_trades": block,
        "resamples": samples,
        "seed": seed,
    }


def prospective_holdout_report(
    candles: list[Candle],
    holdout_start: str,
    min_holdout_trades: int = 30,
    bootstrap_samples: int = 1000,
    config: BacktestConfig = BacktestConfig(),
) -> dict[str, Any]:
    """Evaluate frozen candidates only on observations strictly after the freeze date.

    Pre-cutoff candles are indicator warm-up only. No pre-cutoff signal may enter
    the holdout. Development excludes the holdout start date; holdout candles on
    or after that date are included.
    """
    from datetime import date
    import hashlib

    if min_holdout_trades < 1 or bootstrap_samples < 100:
        raise ValueError("min_holdout_trades must be >= 1 and bootstrap_samples >= 100")
    rows = validate_candles(candles)
    cutoff = date.fromisoformat(holdout_start)
    holdout_indices = [i for i, candle in enumerate(rows) if candle.timestamp.date() >= cutoff]
    if not holdout_indices:
        return {
            "status": "WAITING_FOR_PROSPECTIVE_DATA",
            "candidate_set_version": CANDIDATE_SET_VERSION,
            "execution_config": {
                "fee_per_side": config.fee_per_side,
                "slippage_per_side": config.slippage_per_side,
                "stop_pct": config.stop_pct,
                "target_pct": config.target_pct,
                "max_bars": config.max_bars,
            },
            "holdout_start": holdout_start,
            "holdout_bars": 0,
            "strategies": {
                name: {"status": "NO_HOLDOUT_DATA", "closed_trades": 0}
                for name in REGISTERED_CANDIDATES
            },
            "warning": "No observations on or after the frozen holdout start date.",
        }

    first_index = holdout_indices[0]
    signals = [
        signal for signal in generate_signals(rows)
        if signal.index >= first_index and signal.index < len(rows) - 1
    ]
    trades = backtest(rows, signals, config)
    strategy_results = {}
    for name in REGISTERED_CANDIDATES:
        selected = [
            trade for trade in trades
            if trade.strategy == name and trade.status == "CLOSED" and trade.net_return is not None
            and trade.signal_time.date() >= cutoff
        ]
        values = [float(trade.net_return) for trade in selected]
        n = len(values)
        positive = sum(value > 0 for value in values)
        hac_test = _newey_west_mean_test(values)
        seed_material = f"{name}|{holdout_start}|{rows[-1].timestamp.isoformat()}"
        seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:8], 16)
        ci = _block_bootstrap_mean_ci(values, samples=bootstrap_samples, seed=seed)
        adequately_sampled = n >= min_holdout_trades
        strategy_results[name] = {
            "status": "AWAITING_MULTIPLE_TEST_CORRECTION" if adequately_sampled
                      else "INSUFFICIENT_PROSPECTIVE_SAMPLE",
            "closed_trades": n,
            "positive_trades": positive,
            "win_rate": positive / n if n else None,
            "average_net_return": sum(values) / n if n else None,
            "median_net_return": sorted(values)[n // 2] if n and n % 2 else
                                 ((sorted(values)[n // 2 - 1] + sorted(values)[n // 2]) / 2 if n else None),
            "block_bootstrap_mean_ci_95": ci,
            "raw_hac_pvalue": hac_test["pvalue"],
            "hac_z_statistic": hac_test["z_statistic"],
            "hac_lags": hac_test["lags"],
            "pvalue_method": "one-sided Newey-West HAC normal approximation for mean net trade return",
            "minimum_trades_required": min_holdout_trades,
            "holm_adjusted_pvalue": None,
        }
    return {
        "status": "PROSPECTIVE_DATA_AVAILABLE",
        "method": "frozen candidate set; signal close then next available open; pre-cutoff history is indicator warm-up only",
        "candidate_set_version": CANDIDATE_SET_VERSION,
        "execution_config": {
            "fee_per_side": config.fee_per_side,
            "slippage_per_side": config.slippage_per_side,
            "stop_pct": config.stop_pct,
            "target_pct": config.target_pct,
            "max_bars": config.max_bars,
        },
        "holdout_start": holdout_start,
        "first_holdout_bar": rows[first_index].timestamp.isoformat(),
        "last_bar": rows[-1].timestamp.isoformat(),
        "holdout_bars": len(holdout_indices),
        "strategies": strategy_results,
        "warning": "Prospective research only. A passing statistical screen is not proof of profitability or production approval.",
    }


def apply_holm_correction(results: dict[str, dict[str, Any]], family_size: int | None = None) -> dict[str, Any]:
    """Apply Holm step-down FWER correction across the complete ticker/candidate family."""
    tests = []
    for ticker, item in results.items():
        holdout = item.get("prospective_holdout", {})
        for strategy, detail in holdout.get("strategies", {}).items():
            pvalue = detail.get("raw_hac_pvalue")
            if pvalue is not None and detail.get("closed_trades", 0) >= detail.get("minimum_trades_required", 30):
                tests.append((float(pvalue), ticker, strategy))
    total = family_size if family_size is not None else len(results) * len(REGISTERED_CANDIDATES)
    ordered = sorted(tests)
    if total < len(ordered):
        raise ValueError("family_size cannot be smaller than the number of eligible tests")
    previous_adjusted = 0.0
    for rank, (pvalue, ticker, strategy) in enumerate(ordered, start=1):
        adjusted = min(1.0, max(previous_adjusted, (total - rank + 1) * pvalue))
        previous_adjusted = adjusted
        detail = results[ticker]["prospective_holdout"]["strategies"][strategy]
        detail["holm_adjusted_pvalue"] = adjusted
        ci = detail.get("block_bootstrap_mean_ci_95")
        ci_positive = bool(ci and ci["lower"] > 0)
        detail["status"] = (
            "HOLM_AND_BOOTSTRAP_PASS_FOR_REVIEW"
            if adjusted <= 0.05 and ci_positive
            else "NOT_CONFIRMED_BY_CORRECTED_TEST"
        )
    return {
        "method": "Holm-Bonferroni step-down family-wise error correction",
        "family_size": total,
        "eligible_tests": len(ordered),
        "family_alpha": 0.05,
        "pvalue_test": "one-sided Newey-West HAC normal approximation for mean net trade return",
        "confidence_interval": "95% moving-block bootstrap percentile CI for mean net trade return",
        "note": "Unsampled hypotheses remain in the family-size denominator. Passing is only a research result.",
    }
