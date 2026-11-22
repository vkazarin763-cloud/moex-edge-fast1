"""Extended chronological discovery-power screen on frozen MOEX history."""
from __future__ import annotations

from typing import Any

from .moex_runner import run_moex_d1_research
from .multiple_testing import holm_bonferroni


def run_rolling_moex_d1_research(
    dataset: dict[str, Any],
    *,
    window_starts: tuple[float, ...] = (0.35,),
    window_width: float = 0.60,
    max_hypotheses_per_symbol: int = 200,
    max_optimized_candidates_per_direction: int = 5,
    resamples: int = 199_999,
    **kwargs: Any,
) -> dict[str, Any]:
    """Generate on expanding prefixes and evaluate on non-overlapping later windows.

    All fold/candidate p-values are pooled into one Holm family. Overlapping
    formation histories are intentional; validation windows do not overlap.
    This is robustness research, not an untouched final holdout.
    """
    if not isinstance(dataset, dict) or not isinstance(dataset.get("symbols"), dict):
        raise ValueError("dataset must contain symbols")
    if not window_starts or any(not 0.2 <= x < 0.9 for x in window_starts):
        raise ValueError("window_starts must be non-empty fractions in [0.2, 0.9)")
    if not 0.05 <= window_width <= 0.70:
        raise ValueError("window_width must be between 0.05 and 0.70")
    if isinstance(max_hypotheses_per_symbol, bool) or max_hypotheses_per_symbol < 1:
        raise ValueError("max_hypotheses_per_symbol must be positive")

    # Define boundaries on the shared exchange calendar, not per-symbol
    # bar counts (listing dates differ across the universe).
    calendar = sorted({
        row["timestamp"][:10]
        for rows in dataset["symbols"].values()
        for row in rows
    })
    folds: list[dict[str, Any]] = []
    pooled: dict[str, float] = {}
    pooled_rows: dict[str, dict[str, Any]] = {}
    for fold_index, start_fraction in enumerate(window_starts, 1):
        end_fraction = start_fraction + window_width
        if end_fraction > 0.99:
            continue
        train_cutoff = calendar[min(len(calendar) - 1, int(len(calendar) * start_fraction))]
        eval_cutoff = calendar[min(len(calendar) - 1, int(len(calendar) * end_fraction) - 1)]
        fold_symbols: dict[str, list[dict[str, Any]]] = {}
        formation_ends: dict[str, int] = {}
        for symbol, rows in dataset["symbols"].items():
            prefix = [row for row in rows if row["timestamp"][:10] <= eval_cutoff]
            train_count = sum(row["timestamp"][:10] <= train_cutoff for row in prefix)
            validation_count = len(prefix) - train_count
            if train_count < 40 or validation_count < 10:
                continue
            fold_symbols[symbol] = prefix
            formation_ends[symbol] = train_count
        if not fold_symbols:
            continue
        fold_dataset = dict(dataset)
        fold_dataset["symbols"] = fold_symbols
        fold_dataset["universe_size"] = len(fold_symbols)
        fold_dataset["total_pre_holdout_bars"] = sum(map(len, fold_symbols.values()))
        result = run_moex_d1_research(
            fold_dataset,
            formation_end_by_symbol=formation_ends,
            max_hypotheses_per_symbol=max_hypotheses_per_symbol,
            max_optimized_candidates_per_direction=max_optimized_candidates_per_direction,
            resamples=resamples,
            **kwargs,
        )
        fold_id = f"expanding-{fold_index}-{train_cutoff}-{eval_cutoff}"
        folds.append({
            "fold_id": fold_id,
            "formation_cutoff_date": train_cutoff,
            "evaluation_cutoff_date": eval_cutoff,
            "symbols_processed": result["summary"]["symbols_processed"],
            "hypotheses": result["summary"]["hypotheses_in_global_family"],
            "tested": result["summary"]["hypotheses_with_valid_bootstrap_tests"],
            "underpowered": result["summary"]["underpowered_hypotheses"],
        })
        for symbol, item in result.get("per_symbol", {}).items():
            pipe = item.get("pipeline") or {}
            for row in pipe.get("results", []):
                key = f"{fold_id}:{symbol}:{row.get('candidate_id', row['hypothesis']['id'])}"
                p = row["inference"]["two_sided_p_value"] if row.get("inference") else 1.0
                pooled[key] = p
                pooled_rows[key] = {
                    "fold_id": fold_id, "symbol": symbol,
                    "direction": row["hypothesis"]["direction"],
                    "entry_combination": row["hypothesis"].get("combination", "ALL"),
                    "entry_rule": row["hypothesis"]["conditions"],
                    "exit_combination": row["exit_hypothesis"].get("combination", "ALL"),
                    "exit_rule": row["exit_hypothesis"]["conditions"],
                    "closed_trades": row["closed_trade_count"],
                    "formation_optimization_metrics": row.get("optimization_metrics"),
                    "inference": row.get("inference"),
                    "inference_status": row["inference_status"],
                }

    if not pooled:
        return {
            "status": "NO_ELIGIBLE_WINDOWS",
            "folds": folds,
            "summary": {"folds_completed": len(folds), "hypotheses": 0, "candidates_for_walk_forward": 0},
            "safety": {"strategy_approval": "NOT_APPROVED", "final_holdout_used": False},
        }

    correction = holm_bonferroni(
        pooled, alpha=float(kwargs.get("alpha", 0.05)),
        family_id=f"moex-d1-rolling-global-{dataset.get('holdout_start', 'sealed')}",
    )
    adjusted = {x["hypothesis_id"]: x for x in correction["results"]}
    candidates = []
    tested = 0
    for key, row in pooled_rows.items():
        adj = adjusted[key]
        inf = row["inference"]
        interval = inf["confidence_interval"] if inf else None
        eligible = bool(
            row["inference_status"] == "TESTED"
            and adj["reject_null"]
            and interval is not None
            and interval["lower"] > 0
        )
        row["global_multiple_testing"] = adj
        row["status"] = "CANDIDATE_FOR_WALK_FORWARD" if eligible else (
            "INSUFFICIENT_DATA" if inf is None else "NOT_SELECTED"
        )
        tested += int(inf is not None)
        if eligible:
            candidates.append({
                "fold_id": row["fold_id"], "symbol": row["symbol"],
                "direction": row["direction"],
                "entry_combination": row["entry_combination"], "entry_rule": row["entry_rule"],
                "exit_combination": row["exit_combination"], "exit_rule": row["exit_rule"],
                "closed_trades": row["closed_trades"],
                "mean_net_return": inf["observed_mean"],
                "confidence_interval": interval,
                "global_adjusted_p_value": adj["holm_adjusted_p_value"],
            })

    return {
        "status": "COMPLETED",
        "data": {
            "source": "MOEX ISS native TQBR D1 history",
            "generated_at_utc": dataset.get("generated_at_utc"),
            "holdout_start": dataset.get("holdout_start"),
            "universe_size": dataset.get("universe_size"),
            "sealed_final_holdout_used": False,
        },
        "research_design": {
            "method": "single extended chronological evaluation window for discovery power screening",
            "purpose": "increase out-of-sample trade observations per frozen candidate before a separate multi-fold walk-forward stage",
            "window_starts": list(window_starts),
            "window_width": window_width,
            "calendar_aligned_boundaries": True,
            "all_folds_and_symbols_in_one_global_holm_family": True,
            "formation_only_hypothesis_generation": True,
            "formation_return_optimization_before_validation": True,
            "optimized_shortlist_per_direction": max_optimized_candidates_per_direction,
            "validation_windows_non_overlapping": True,
            "overlapping_formation_prefixes": False,
            "single_extended_validation_window": len(folds) == 1,
            "this_is_not_an_untouched_final_holdout": True,
            "strategy_approval": "NOT_APPROVED",
        },
        "folds": folds,
        "global_family": correction,
        "summary": {
            "folds_completed": len(folds),
            "hypotheses": len(pooled),
            "hypotheses_with_valid_bootstrap_tests": tested,
            "underpowered_hypotheses": len(pooled) - tested,
            "candidates_for_walk_forward": len(candidates),
        },
        "candidates_for_walk_forward": candidates,
        "results": pooled_rows,
        "safety": {
            "lookahead_used": False,
            "final_holdout_used": False,
            "capital_or_position_sizing_used": False,
            "broker_or_live_trading_accessed": False,
            "strategy_approval": "NOT_APPROVED",
        },
    }


def main() -> int:
    import argparse
    import json
    from pathlib import Path
    from .moex_dataset import load_pre_holdout_d1

    parser = argparse.ArgumentParser(description="Run expanding-window autonomous MOEX D1 research")
    parser.add_argument("--data", required=True)
    parser.add_argument("--validation", required=True)
    parser.add_argument("--output", default="moex_edge_v2_rolling_research.json")
    parser.add_argument("--holdout-start", default="2026-11-20")
    parser.add_argument("--max-hypotheses-per-symbol", type=int, default=200)
    parser.add_argument("--max-optimized-candidates-per-direction", type=int, default=5)
    parser.add_argument("--resamples", type=int, default=199_999)
    args = parser.parse_args()
    dataset = load_pre_holdout_d1(
        args.data, args.validation, holdout_start=args.holdout_start
    )
    result = run_rolling_moex_d1_research(
        dataset,
        max_hypotheses_per_symbol=args.max_hypotheses_per_symbol,
        max_optimized_candidates_per_direction=args.max_optimized_candidates_per_direction,
        resamples=args.resamples,
    )
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": result["status"],
        "summary": result.get("summary"),
        "folds": result.get("folds"),
        "safety": result.get("safety"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
