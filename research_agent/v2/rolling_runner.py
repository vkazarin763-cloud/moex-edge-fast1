"""Expanding-window research over several chronological MOEX periods."""
from __future__ import annotations

from typing import Any

from .moex_runner import run_moex_d1_research
from .multiple_testing import holm_bonferroni


def run_rolling_moex_d1_research(
    dataset: dict[str, Any],
    *,
    window_starts: tuple[float, ...] = (0.50, 0.65, 0.80),
    window_width: float = 0.15,
    max_hypotheses_per_symbol: int = 10,
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
    if not 0.05 <= window_width <= 0.3:
        raise ValueError("window_width must be between 0.05 and 0.30")
    if isinstance(max_hypotheses_per_symbol, bool) or max_hypotheses_per_symbol < 1:
        raise ValueError("max_hypotheses_per_symbol must be positive")

    minimum_length = min(len(rows) for rows in dataset["symbols"].values())
    folds: list[dict[str, Any]] = []
    pooled: dict[str, float] = {}
    pooled_rows: dict[str, dict[str, Any]] = {}
    for fold_index, start_fraction in enumerate(window_starts, 1):
        end_fraction = start_fraction + window_width
        if end_fraction > 0.99:
            continue
        fold_symbols = {}
        fold_dates = []
        for symbol, rows in dataset["symbols"].items():
            n = len(rows)
            train_end = int(n * start_fraction)
            eval_end = min(n, int(n * end_fraction))
            if train_end < 40 or eval_end - train_end < 10:
                continue
            fold_symbols[symbol] = list(rows[:eval_end])
            fold_dates.extend([rows[train_end]["timestamp"][:10], rows[eval_end - 1]["timestamp"][:10]])
        if not fold_symbols:
            continue
        # The runner expects one aligned universe. Symbols lacking sufficient
        # history are omitted for this fold, never padded or forward-filled.
        fold_dataset = dict(dataset)
        fold_dataset["symbols"] = fold_symbols
        fold_dataset["universe_size"] = len(fold_symbols)
        fold_dataset["total_pre_holdout_bars"] = sum(map(len, fold_symbols.values()))
        result = run_moex_d1_research(
            fold_dataset,
            formation_fraction= start_fraction / end_fraction,
            max_hypotheses_per_symbol=max_hypotheses_per_symbol,
            resamples=resamples,
            **kwargs,
        )
        fold_id = f"expanding-{fold_index}-{start_fraction:.2f}-{end_fraction:.2f}"
        folds.append({
            "fold_id": fold_id,
            "formation_fraction_of_full_history": start_fraction,
            "evaluation_end_fraction_of_full_history": end_fraction,
            "evaluation_windows_non_overlapping": True,
            "symbols_processed": result["summary"]["symbols_processed"],
            "hypotheses": result["summary"]["hypotheses_in_global_family"],
            "tested": result["summary"]["hypotheses_with_valid_bootstrap_tests"],
            "underpowered": result["summary"]["underpowered_hypotheses"],
            "first_evaluation_date": min(fold_dates) if fold_dates else None,
            "last_evaluation_date": max(fold_dates) if fold_dates else None,
        })
        for symbol, item in result.get("per_symbol", {}).items():
            pipe = item.get("pipeline") or {}
            for row in pipe.get("results", []):
                key = f"{fold_id}:{symbol}:{row.get('candidate_id', row['hypothesis']['id'])}"
                p = row["inference"]["two_sided_p_value"] if row.get("inference") else 1.0
                pooled[key] = p
                pooled_rows[key] = {
                    "fold_id": fold_id,
                    "symbol": symbol,
                    "direction": row["hypothesis"]["direction"],
                    "entry_rule": row["hypothesis"]["conditions"],
                    "exit_rule": row["exit_hypothesis"]["conditions"],
                    "closed_trades": row["closed_trade_count"],
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
                "direction": row["direction"], "entry_rule": row["entry_rule"],
                "exit_rule": row["exit_rule"], "closed_trades": row["closed_trades"],
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
            "method": "expanding formation windows with sequential non-overlapping evaluation windows",
            "window_starts": list(window_starts),
            "window_width": window_width,
            "all_folds_and_symbols_in_one_global_holm_family": True,
            "formation_only_hypothesis_generation": True,
            "validation_windows_non_overlapping": True,
            "overlapping_formation_prefixes": True,
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
