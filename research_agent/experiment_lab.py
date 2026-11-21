"""Deterministic, read-only experiment runner for exit-policy hypotheses.

This Research Lab explores execution/exit configurations only. It reuses the
frozen entry formulas and primary simulator, then independently replays the
resulting signals as an execution-integrity audit. It never changes the frozen
prospective cohort or evaluates candles on/after the holdout boundary.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from .core import BacktestConfig, Candle, backtest, generate_signals
from .reference_audit import compare_replay, reference_replay
from .reference_signals import audit_signal_generation
from .validation import walk_forward_report, adversarial_cost_check

HOLDOUT_START = date(2026, 11, 20)


@dataclass(frozen=True)
class ExitHypothesis:
    hypothesis_id: str
    description: str
    config: BacktestConfig


DEFAULT_EXIT_HYPOTHESES = (
    ExitHypothesis(
        "exit-baseline-3pct-6pct-120",
        "Reference execution policy; unchanged frozen-cohort assumptions.",
        BacktestConfig(0.001, 0.0005, 0.03, 0.06, 120),
    ),
    ExitHypothesis(
        "exit-tight-2pct-4pct-60",
        "Tighter fixed stop/target and shorter maximum holding horizon.",
        BacktestConfig(0.001, 0.0005, 0.02, 0.04, 60),
    ),
    ExitHypothesis(
        "exit-wide-4pct-8pct-180",
        "Wider fixed stop/target and longer maximum holding horizon.",
        BacktestConfig(0.001, 0.0005, 0.04, 0.08, 180),
    ),
)


def _dataset_fingerprint(rows: list[Candle]) -> str:
    payload = [
        [c.timestamp.isoformat(), c.open, c.high, c.low, c.close, c.volume]
        for c in rows
    ]
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _execution_replay_audit(rows: list[Candle], config: BacktestConfig) -> dict[str, Any]:
    """Compare primary execution against a separately implemented reference replay."""
    signals = generate_signals(rows)
    primary = backtest(rows, signals, config)
    reference = reference_replay(rows, signals, config)
    return compare_replay(primary, reference)


def run_experiment_lab(
    candles_by_ticker: dict[str, list[Candle]],
    *,
    hypotheses: tuple[ExitHypothesis, ...] = DEFAULT_EXIT_HYPOTHESES,
    holdout_start: str = HOLDOUT_START.isoformat(),
    folds: int = 4,
    warmup_bars: int = 200,
    min_total_trades: int = 30,
    min_trades_per_fold: int = 5,
) -> dict[str, Any]:
    """Run every registered exit hypothesis on development-only D1 candles.

    All trials are retained, including insufficient samples and rejected results.
    Completed trials carry independent signal-formula and execution replay
    comparisons. The full hypothesis family size is reported so exploratory screens cannot be
    mistaken for multiplicity-adjusted inference.
    """
    cutoff = date.fromisoformat(holdout_start)
    if not hypotheses:
        raise ValueError("At least one exit hypothesis is required")
    ids = [item.hypothesis_id for item in hypotheses]
    if len(set(ids)) != len(ids) or any(not value.strip() for value in ids):
        raise ValueError("Hypothesis IDs must be non-empty and unique")

    trials: list[dict[str, Any]] = []
    tickers = sorted(candles_by_ticker)
    for ticker in tickers:
        rows = candles_by_ticker[ticker]
        development = [c for c in rows if c.timestamp.date() < cutoff]
        excluded_holdout = sum(c.timestamp.date() >= cutoff for c in rows)
        fingerprint = _dataset_fingerprint(development) if development else None
        for hypothesis in hypotheses:
            record: dict[str, Any] = {
                "ticker": ticker,
                "hypothesis_id": hypothesis.hypothesis_id,
                "description": hypothesis.description,
                "execution_config": asdict(hypothesis.config),
                "development_bars": len(development),
                "excluded_holdout_bars": excluded_holdout,
                "development_data_sha256": fingerprint,
            }
            try:
                walk = walk_forward_report(
                    development,
                    folds=folds,
                    warmup_bars=warmup_bars,
                    min_total_trades=min_total_trades,
                    min_trades_per_fold=min_trades_per_fold,
                    config=hypothesis.config,
                )
                stress = adversarial_cost_check(
                    development,
                    folds=folds,
                    warmup_bars=warmup_bars,
                    min_total_trades=min_total_trades,
                    min_trades_per_fold=min_trades_per_fold,
                    config=hypothesis.config,
                )
                signals = generate_signals(development)
                signal_audit = audit_signal_generation(development, signals)
                replay_audit = _execution_replay_audit(development, hypothesis.config)
                record.update({
                    "status": "EXPERIMENTAL_SCREEN_COMPLETE",
                    "walk_forward": walk,
                    "adversarial_cost_check": stress,
                    "signal_generation_audit": signal_audit,
                    "execution_replay_audit": replay_audit,
                })
            except (ValueError, TypeError) as exc:
                record.update({
                    "status": "INSUFFICIENT_OR_INVALID_DEVELOPMENT_DATA",
                    "reason": str(exc),
                })
            trials.append(record)

    completed = sum(t["status"] == "EXPERIMENTAL_SCREEN_COMPLETE" for t in trials)
    return {
        "lab_version": "exit-policy-experiments-v1",
        "status": "EXPERIMENT_LAB_COMPLETE",
        "generated_scope": "development_history_only",
        "holdout_start": cutoff.isoformat(),
        "holdout_policy": "All bars on/after holdout_start are excluded before any test.",
        "hypothesis_family": "fixed-entry-formulas x exit-policy-variants",
        "hypothesis_ids": ids,
        "hypothesis_configs": {
            item.hypothesis_id: asdict(item.config) for item in hypotheses
        },
        "hypothesis_count": len(hypotheses),
        "entry_strategy_ids": [
            "Donchian20", "EMA20x50", "RSI14Trend50",
            "MACD12x26", "Keltner20x2ATR",
        ],
        "entry_strategy_count": 5,
        "ticker_ids": tickers,
        "ticker_count": len(tickers),
        "multiple_testing_family_size": len(tickers) * len(hypotheses) * 5,
        "trials_total": len(trials),
        "trials_completed": completed,
        "trials_incomplete": len(trials) - completed,
        "trials": trials,
        "interpretation": (
            "Exploratory development screening only. Results are not holdout evidence, "
            "not multiplicity-adjusted statistical conclusions, not live signals, "
            "and cannot modify the frozen v1 candidate cohort. Independent signal "
            "replay checks event parity for the five frozen formulas; neither signal "
            "nor execution replay verifies raw-data provenance."
        ),
        "safety": "Read-only. No broker API, order placement, or production-state writes.",
    }
