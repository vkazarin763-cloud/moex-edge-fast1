"""Chronological walk-forward evaluation and conservative candidate gating."""
from __future__ import annotations

import math
from typing import Any

from .core import BacktestConfig, Candle, backtest, generate_signals, summarize, validate_candles


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
        fold_reports.append({
            "fold": fold + 1,
            "start": rows[start].timestamp.isoformat(),
            "end_inclusive": rows[end - 1].timestamp.isoformat(),
            "strategies": per_strategy,
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
            "status": "PROMISING_FOR_INDEPENDENT_REVIEW" if passes else "REJECT_OR_INSUFFICIENT_EVIDENCE",
        }
    return {
        "method": "expanding-history indicators; sequential non-overlapping test folds; fixed candidates",
        "candles": len(rows),
        "warmup_bars": warmup_bars,
        "folds": fold_reports,
        "candidates": candidates,
        "warning": "Exploratory evidence only. No multiple-testing correction, bootstrap confidence intervals, cross-symbol portfolio simulation, or production approval.",
    }

from dataclasses import replace


def adversarial_cost_check(candles: list[Candle], folds: int = 4,
                           warmup_bars: int = 200,
                           min_total_trades: int = 30,
                           min_trades_per_fold: int = 5,
                           config: BacktestConfig = BacktestConfig()) -> dict[str, Any]:
    """Re-run the same fixed hypotheses with doubled fees and slippage.

    This is an execution-cost sensitivity test, not independent data validation.
    """
    baseline = walk_forward_report(
        candles, folds, warmup_bars, min_total_trades, min_trades_per_fold, config
    )
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
            stress
            and stress["status"] == "PROMISING_FOR_INDEPENDENT_REVIEW"
            and stress["average_net_return"] is not None
            and stress["average_net_return"] > 0
        )
        results[strategy] = {
            "baseline_status": base["status"],
            "double_cost_status": stress["status"] if stress else "NO_STRESS_SAMPLE",
            "survives_double_costs": survives,
            "baseline_average_net_return": base["average_net_return"],
            "double_cost_average_net_return": stress["average_net_return"] if stress else None,
        }
    return {
        "stress": "2x entry/exit fees and slippage",
        "candidates": results,
        "warning": "Cost sensitivity only; it does not replace a separate holdout dataset or independent review.",
    }
