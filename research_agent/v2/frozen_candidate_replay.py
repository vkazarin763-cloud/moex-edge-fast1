"""Replay a previously selected MOEX D1 candidate on a fixed, later date window.

This command does not generate, optimize, or select rules. It loads the exact
candidate rules from a prior research report, rebuilds causal D1 features from
the validated frozen dataset, and evaluates only the requested date window.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from .cross_sectional import extract_cross_sectional_features
from .execution import evaluate_hypothesis
from .features import extract_ohlcv_features
from .moex_dataset import load_pre_holdout_d1


def find_candidate(report: dict[str, Any], symbol: str, direction: str) -> dict[str, Any]:
    candidates = report.get("candidates_for_walk_forward")
    if not isinstance(candidates, list):
        raise ValueError("candidate report has no candidates_for_walk_forward list")
    matches = [
        row for row in candidates
        if row.get("symbol") == symbol and row.get("direction") == direction
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one frozen {symbol} {direction} candidate; found {len(matches)}"
        )
    candidate = dict(matches[0])
    fold_id = candidate.get("fold_id")
    folds = report.get("folds")
    if not isinstance(fold_id, str) or not isinstance(folds, list):
        raise ValueError("candidate report must identify the selection fold")
    fold_matches = [fold for fold in folds if fold.get("fold_id") == fold_id]
    if len(fold_matches) != 1 or not fold_matches[0].get("evaluation_cutoff_date"):
        raise ValueError("candidate selection cutoff cannot be established")
    candidate["selection_cutoff_date"] = fold_matches[0]["evaluation_cutoff_date"]
    for field in ("entry_combination", "entry_rule", "exit_combination", "exit_rule"):
        if field not in candidate:
            raise ValueError(f"candidate is missing {field}")
    return candidate


def replay_frozen_candidate(
    dataset: dict[str, Any],
    candidate: dict[str, Any],
    *,
    start_date: str,
    end_date: str,
    commission_rate: float = 0.0008,
    slippage_rate: float = 0.0005,
) -> dict[str, Any]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    holdout = date.fromisoformat(dataset["holdout_start"])
    if start > end:
        raise ValueError("start_date must not be after end_date")
    if end >= holdout:
        raise ValueError("replay window must end before the sealed holdout")
    selection_cutoff = candidate.get("selection_cutoff_date")
    if not isinstance(selection_cutoff, str):
        raise ValueError("candidate selection cutoff is required to prevent post-selection leakage")
    if start <= date.fromisoformat(selection_cutoff):
        raise ValueError("replay must start strictly after the candidate selection cutoff")
    symbol = candidate.get("symbol")
    direction = candidate.get("direction")
    if direction not in ("LONG", "SHORT"):
        raise ValueError("candidate direction must be LONG or SHORT")
    symbols = dataset.get("symbols")
    if not isinstance(symbols, dict) or symbol not in symbols:
        raise ValueError(f"candidate symbol {symbol!r} is absent from the dataset")

    # Features are calculated over the complete pre-holdout history first;
    # only then are the bars/panels sliced to the requested replay window.
    # Each feature at t remains causal and uses no observations after t.
    base = {
        name: extract_ohlcv_features(rows)
        for name, rows in symbols.items()
    }
    cross = extract_cross_sectional_features(
        symbols, horizons=(5, 20), min_coverage_fraction=0.5
    )
    full_panel = dict(base[symbol])
    full_panel.update(cross[symbol])
    full_bars = symbols[symbol]
    indices = [
        i for i, bar in enumerate(full_bars)
        if start <= date.fromisoformat(bar["timestamp"][:10]) <= end
    ]
    if len(indices) < 2:
        raise ValueError("replay window must contain at least two observed D1 bars")
    first, last = indices[0], indices[-1]
    bars = full_bars[first:last + 1]
    panel = {name: values[first:last + 1] for name, values in full_panel.items()}

    entry = {
        "direction": direction,
        "combination": candidate["entry_combination"],
        "conditions": candidate["entry_rule"],
    }
    exit_rule = {
        "direction": direction,
        "combination": candidate["exit_combination"],
        "conditions": candidate["exit_rule"],
    }

    scenarios = []
    for multiplier in (1, 2, 3):
        result = evaluate_hypothesis(
            bars,
            panel,
            entry,
            exit_rule,
            commission_rate=commission_rate * multiplier,
            slippage_rate=slippage_rate * multiplier,
        )
        scenarios.append({
            "cost_multiplier": multiplier,
            "commission_rate_per_side": commission_rate * multiplier,
            "slippage_rate_per_side": slippage_rate * multiplier,
            "closed_trades": result["counts"]["closed_trades"],
            "mean_net_return": result["metrics"]["mean_net_return"],
            "total_net_return_sum": result["metrics"]["total_net_return_sum"],
            "trades": result["trades"],
            "open_position_at_window_end": result["open_position"],
        })

    return {
        "status": "COMPLETED",
        "data": {
            "source": "MOEX ISS native TQBR D1",
            "generated_at_utc": dataset["generated_at_utc"],
            "holdout_start": dataset["holdout_start"],
            "universe_size": dataset["universe_size"],
            "symbol": symbol,
            "first_replay_bar": bars[0]["timestamp"][:10],
            "last_replay_bar": bars[-1]["timestamp"][:10],
            "replay_bars": len(bars),
            "candidate_rules_changed": False,
        },
        "candidate": {
            "direction": direction,
            "entry_combination": candidate["entry_combination"],
            "entry_rule": candidate["entry_rule"],
            "exit_combination": candidate["exit_combination"],
            "exit_rule": candidate["exit_rule"],
        },
        "cost_sensitivity": scenarios,
        "safety": {
            "rules_generated_or_optimized": False,
            "replay_rows_used_for_rule_selection": False,
            "lookahead_used": False,
            "sealed_holdout_used": False,
            "capital_or_position_sizing_used": False,
            "broker_or_live_trading_accessed": False,
            "strategy_approval": "NOT_APPROVED",
            "statistical_significance_claimed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay one frozen MOEX D1 candidate without strategy optimization"
    )
    parser.add_argument("--data", required=True)
    parser.add_argument("--validation", required=True)
    parser.add_argument("--candidate-report", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--direction", choices=("LONG", "SHORT"), required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--holdout-start", default="2026-11-20")
    parser.add_argument("--output", default="moex_frozen_candidate_replay.json")
    args = parser.parse_args()

    dataset = load_pre_holdout_d1(
        args.data, args.validation, holdout_start=args.holdout_start
    )
    report = json.loads(Path(args.candidate_report).read_text(encoding="utf-8"))
    report_data = report.get("data", {})
    if report_data.get("generated_at_utc") != dataset["generated_at_utc"]:
        raise ValueError("candidate report and dataset provenance timestamps do not match")
    if report_data.get("holdout_start") != dataset["holdout_start"]:
        raise ValueError("candidate report and dataset holdout boundaries do not match")
    candidate = find_candidate(report, args.symbol, args.direction)
    result = replay_frozen_candidate(
        dataset, candidate,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": result["status"],
        "data": result["data"],
        "cost_sensitivity": [
            {
                "cost_multiplier": row["cost_multiplier"],
                "closed_trades": row["closed_trades"],
                "mean_net_return": row["mean_net_return"],
            }
            for row in result["cost_sensitivity"]
        ],
        "safety": result["safety"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
