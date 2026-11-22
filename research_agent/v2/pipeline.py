"""Formation-driven optimization followed by a later chronological evaluation.

The optimizer may fit and rank many entry/exit combinations on the historical
formation prefix. Only frozen top rules are passed to the later validation
window. Validation returns never influence generation, ranking, or selection.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import sqrt
from statistics import median
from typing import Any

from .bootstrap import moving_block_bootstrap_mean_test
from .discovery import generate_hypotheses, generate_exit_hypotheses
from .evolutionary import expand_hypotheses
from .execution import evaluate_hypothesis
from .multiple_testing import holm_bonferroni


class PipelineInputError(ValueError):
    """Invalid chronological split or research-pipeline configuration."""


def _optimization_metrics(execution: Mapping[str, Any]) -> dict[str, float | int]:
    returns = [float(trade["net_return"]) for trade in execution["trades"]]
    count = len(returns)
    if not returns:
        return {
            "closed_trades": 0, "mean_net_return": 0.0,
            "median_net_return": 0.0, "profit_factor": 0.0,
            "max_drawdown": 1.0, "optimization_score": -1.0,
        }
    wins = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value < 0))
    equity = peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity *= max(0.0, 1.0 + value)
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, 1.0 - equity / peak)
    mean_value = sum(returns) / count
    # Shrink noisy small samples and penalize deep trade-sequence drawdowns.
    score = mean_value * sqrt(count / (count + 10.0)) - 0.25 * max_drawdown
    return {
        "closed_trades": count,
        "mean_net_return": mean_value,
        "median_net_return": median(returns),
        "profit_factor": wins / losses if losses > 0 else (999.0 if wins > 0 else 0.0),
        "max_drawdown": max_drawdown,
        "optimization_score": score,
    }


def run_research_pipeline(
    bars: Sequence[Mapping[str, Any]],
    feature_panel: Mapping[str, Sequence[float | None]],
    exit_hypothesis: Mapping[str, Any],
    *,
    formation_end: int,
    max_features: int = 12,
    max_hypotheses: int = 200,
    max_optimized_candidates_per_direction: int = 5,
    min_formation_observations: int = 20,
    min_trades_for_inference: int = 20,
    block_length: int = 5,
    resamples: int = 5000,
    alpha: float = 0.05,
    commission_rate: float = 0.0008,
    slippage_rate: float = 0.0005,
    seed: int = 1729,
    family_id: str = "moex-edge-v2-validation-family",
) -> dict[str, Any]:
    """Optimize on [0, formation_end), evaluate frozen rules on [formation_end, n)."""
    if isinstance(bars, (str, bytes)) or not isinstance(bars, Sequence):
        raise PipelineInputError("bars must be a chronological sequence")
    if isinstance(feature_panel, (str, bytes)) or not isinstance(feature_panel, Mapping) or not feature_panel:
        raise PipelineInputError("feature_panel must be a non-empty mapping")
    n = len(bars)
    if n < 4:
        raise PipelineInputError("at least four bars are required")
    if isinstance(formation_end, bool) or not isinstance(formation_end, int) or not 2 <= formation_end <= n - 2:
        raise PipelineInputError("formation_end must leave at least two bars in each window")
    for name, values in feature_panel.items():
        if not isinstance(name, str) or not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or len(values) != n:
            raise PipelineInputError("every feature series must align with bars")
    if isinstance(min_trades_for_inference, bool) or not isinstance(min_trades_for_inference, int) or min_trades_for_inference < 20:
        raise PipelineInputError("min_trades_for_inference must be an integer >= 20")
    if isinstance(block_length, bool) or not isinstance(block_length, int) or block_length < 1:
        raise PipelineInputError("block_length must be a positive integer")
    if isinstance(max_optimized_candidates_per_direction, bool) or not isinstance(max_optimized_candidates_per_direction, int) or max_optimized_candidates_per_direction < 1:
        raise PipelineInputError("max_optimized_candidates_per_direction must be a positive integer")
    if not isinstance(exit_hypothesis, Mapping):
        raise PipelineInputError("exit_hypothesis mapping is required")
    autonomous_exits = exit_hypothesis.get("mode") == "AUTONOMOUS"
    if not autonomous_exits:
        if "LONG" in exit_hypothesis or "SHORT" in exit_hypothesis:
            for direction in ("LONG", "SHORT"):
                rule = exit_hypothesis.get(direction)
                if not isinstance(rule, Mapping) or not isinstance(rule.get("conditions"), list) or not rule["conditions"]:
                    raise PipelineInputError("directional exit rules must define non-empty LONG and SHORT conditions")
        elif not isinstance(exit_hypothesis.get("conditions"), list) or not exit_hypothesis["conditions"]:
            raise PipelineInputError("exit_hypothesis must contain non-empty conditions")
    if not isinstance(family_id, str) or not family_id.strip():
        raise PipelineInputError("family_id must be a non-empty string")

    formation_bars = list(bars[:formation_end])
    formation_panel = {name: list(values[:formation_end]) for name, values in feature_panel.items()}
    seed_limit = max(1, max_hypotheses // 2)
    seed_discovery = generate_hypotheses(
        formation_panel, formation_indices=list(range(formation_end)),
        max_features=max_features, max_hypotheses=seed_limit,
        min_observations=min_formation_observations,
    )
    evolutionary = expand_hypotheses(
        formation_panel, formation_indices=list(range(formation_end)),
        seed_hypotheses=seed_discovery["hypotheses"],
        max_hypotheses=max(0, max_hypotheses - len(seed_discovery["hypotheses"])),
        max_conditions=4, min_observations=min_formation_observations,
    )
    hypotheses = list(seed_discovery["hypotheses"]) + list(evolutionary["hypotheses"])
    discovery = {
        **seed_discovery,
        "generator": "balanced_seed_plus_evolutionary_mutation_crossover_v1",
        "seed_hypothesis_count": len(seed_discovery["hypotheses"]),
        "evolutionary_expansion": evolutionary,
        "hypotheses": hypotheses,
        "hypothesis_count": len(hypotheses),
        "safety": {
            **seed_discovery["safety"],
            "evolution_uses_formation_only": True,
            "validation_rows_used_for_generation": False,
            "forward_returns_used_for_generation": False,
        },
    }
    if not hypotheses:
        return {
            "status": "NO_CANDIDATES", "discovery": discovery,
            "optimization": {"generated_entry_rules": 0, "evaluated_pairs": 0, "selected_pairs": 0},
            "family": {"family_id": family_id, "family_size": 0},
            "results": [],
            "safety": {"formation_precedes_validation": True,
                       "validation_used_for_generation": False,
                       "strategy_approval": "NOT_APPROVED"},
        }

    # This is deliberately the only stage allowed to rank by historical returns.
    # Its scores are optimization diagnostics, not independent performance claims.
    ranked: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        if autonomous_exits:
            exit_generation = generate_exit_hypotheses(
                formation_panel, formation_indices=list(range(formation_end)),
                entry_hypothesis=hypothesis,
                max_exit_hypotheses=int(exit_hypothesis.get("max_exit_hypotheses", 2)),
                min_observations=min_formation_observations,
            )
            exit_rules = exit_generation["hypotheses"]
        else:
            exit_rules = [(
                exit_hypothesis[hypothesis["direction"]]
                if "LONG" in exit_hypothesis or "SHORT" in exit_hypothesis
                else exit_hypothesis
            )]
        for exit_rule in exit_rules:
            execution = evaluate_hypothesis(
                formation_bars, formation_panel, hypothesis, exit_rule,
                commission_rate=commission_rate, slippage_rate=slippage_rate,
            )
            metrics = _optimization_metrics(execution)
            ranked.append({
                "candidate_id": f"{hypothesis['id']}::{exit_rule['id']}" if autonomous_exits else hypothesis["id"],
                "hypothesis": hypothesis, "exit_hypothesis": exit_rule,
                "optimization_metrics": metrics,
            })

    # Keep the best exit for each entry rule, then retain a balanced LONG/SHORT
    # shortlist. This bounds the later statistical family and avoids one rule
    # consuming the shortlist through several nearly identical exits.
    ranked.sort(key=lambda item: (
        -float(item["optimization_metrics"]["optimization_score"]),
        -int(item["optimization_metrics"]["closed_trades"]),
        item["candidate_id"],
    ))
    selected: list[dict[str, Any]] = []
    seen_entries: set[str] = set()
    counts = {"LONG": 0, "SHORT": 0}
    logic_counts = {
        f"{direction}_{mode}": 0
        for direction in ("LONG", "SHORT") for mode in ("ALL", "ANY")
    }
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {
        (direction, mode): [] for direction in ("LONG", "SHORT")
        for mode in ("ALL", "ANY")
    }
    for item in ranked:
        key = (
            item["hypothesis"]["direction"],
            item["hypothesis"].get("combination", "ALL"),
        )
        if key in buckets:
            buckets[key].append(item)

    # Preserve ALL/ANY representation after formation-return ranking. The
    # earlier direction-only quota let high-scoring ALL rules crowd out ANY.
    # Round-robin is deterministic and still ranks candidates within each
    # direction/logic bucket by the formation-only optimization score.
    while any(buckets.values()):
        added = False
        for direction in ("LONG", "SHORT"):
            if counts[direction] >= max_optimized_candidates_per_direction:
                continue
            for mode in ("ALL", "ANY"):
                bucket = buckets[(direction, mode)]
                while bucket and bucket[0]["hypothesis"]["id"] in seen_entries:
                    bucket.pop(0)
                if not bucket:
                    continue
                item = bucket.pop(0)
                entry_id = item["hypothesis"]["id"]
                if entry_id in seen_entries:
                    continue
                selected.append(item)
                seen_entries.add(entry_id)
                counts[direction] += 1
                logic_counts[f"{direction}_{mode}"] += 1
                added = True
                if counts[direction] >= max_optimized_candidates_per_direction:
                    break
        if not added:
            break
    # If one logic family has too few distinct entries, remaining slots are
    # filled from the other family without duplicating an entry rule.

    validation_bars = list(bars[formation_end:])
    validation_panel = {name: list(values[formation_end:]) for name, values in feature_panel.items()}
    family_p_values: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    for item in selected:
        hypothesis = item["hypothesis"]
        exit_rule = item["exit_hypothesis"]
        candidate_id = item["candidate_id"]
        execution = evaluate_hypothesis(
            validation_bars, validation_panel, hypothesis, exit_rule,
            commission_rate=commission_rate, slippage_rate=slippage_rate,
        )
        returns = [trade["net_return"] for trade in execution["trades"]]
        inference = None
        if len(returns) >= min_trades_for_inference and block_length <= len(returns) // 2:
            inference = moving_block_bootstrap_mean_test(
                returns, block_length=block_length, resamples=resamples,
                alpha=alpha, seed=seed,
            )
            family_p_values[candidate_id] = inference["two_sided_p_value"]
            inference_status = "TESTED"
        else:
            family_p_values[candidate_id] = 1.0
            inference_status = "INSUFFICIENT_DATA"
        rows.append({
            "candidate_id": candidate_id, "hypothesis": hypothesis,
            "exit_hypothesis": exit_rule, "execution": execution,
            "optimization_metrics": item["optimization_metrics"],
            "inference": inference, "inference_status": inference_status,
            "closed_trade_count": len(returns),
            "candidate_for_walk_forward": False, "approval_status": "NOT_APPROVED",
        })

    if not family_p_values:
        return {
            "status": "NO_OPTIMIZABLE_CANDIDATES", "discovery": discovery,
            "optimization": {
                "method": "formation_return_ranked_evolutionary_search",
                "generated_entry_rules": len(hypotheses),
                "evaluated_pairs": len(ranked), "selected_pairs": 0,
                "selected_by_direction": counts,
                "selected_by_direction_and_logic": logic_counts,
                "selection_metric": "shrunk_mean_net_return_minus_drawdown_penalty",
            "evolutionary_expansion": "deterministic mutation and crossover; 3-4 feature conjunctions",
            },
            "family": {"family_id": family_id, "family_size": 0},
            "results": [],
            "safety": {"validation_used_for_optimization": False,
                       "strategy_approval": "NOT_APPROVED"},
        }

    correction = holm_bonferroni(family_p_values, alpha=alpha, family_id=family_id)
    corrected = {item["hypothesis_id"]: item for item in correction["results"]}
    for row in rows:
        adjusted = corrected[row["candidate_id"]]
        row["multiple_testing"] = adjusted
        ci = row["inference"]["confidence_interval"] if row["inference"] else None
        row["candidate_for_walk_forward"] = bool(
            row["inference_status"] == "TESTED" and adjusted["reject_null"]
            and ci is not None and ci["lower"] > 0.0
        )
        if row["inference_status"] == "INSUFFICIENT_DATA":
            row["status"] = "INSUFFICIENT_DATA"
        elif row["candidate_for_walk_forward"]:
            row["status"] = "CANDIDATE_FOR_WALK_FORWARD"
        else:
            row["status"] = "NOT_SELECTED"

    return {
        "status": "COMPLETED",
        "split": {
            "formation_start_index": 0, "formation_end_exclusive": formation_end,
            "validation_start_index": formation_end, "validation_end_exclusive": n,
            "validation_bars": len(validation_bars),
        },
        "discovery": discovery,
        "optimization": {
            "method": "formation_return_ranked_search",
            "generated_entry_rules": len(hypotheses),
            "evaluated_pairs": len(ranked), "selected_pairs": len(selected),
            "selected_by_direction": counts,
            "selected_by_direction_and_logic": logic_counts,
            "selection_metric": "shrunk_mean_net_return_minus_drawdown_penalty",
            "top_rules": [{
                "candidate_id": item["candidate_id"],
                "direction": item["hypothesis"]["direction"],
                "entry_rule": item["hypothesis"]["conditions"],
                "exit_rule": item["exit_hypothesis"]["conditions"],
                **item["optimization_metrics"],
            } for item in selected],
            "formation_returns_used_for_optimization": True,
            "validation_returns_used_for_optimization": False,
        },
        "family": {
            "family_id": family_id,
            "entry_hypotheses_generated": len(hypotheses),
            "exit_entry_pairs_generated": len(ranked),
            "optimized_pairs_selected": len(selected),
            "family_size_generated": len(rows),
            "family_size_corrected": correction["family_size"],
            "underpowered_candidates_retained_with_conservative_p1": True,
            "correction": correction,
        },
        "results": rows,
        "summary": {
            "tested_candidates": sum(row["inference_status"] == "TESTED" for row in rows),
            "underpowered_candidates": sum(row["inference_status"] == "INSUFFICIENT_DATA" for row in rows),
            "walk_forward_candidates": sum(row["candidate_for_walk_forward"] for row in rows),
        },
        "protocol": {
            "exit_rule_predeclared_by_caller": not autonomous_exits,
            "exit_rules_generated_from_formation_only": autonomous_exits,
            "entry_rules_generated_from_formation_only": True,
            "mutation_and_crossover_use_formation_features_only": True,
            "formation_returns_used_for_optimization": True,
            "validation_used_for_optimization": False,
            "validation_used_for_statistical_evaluation_only": True,
            "exit_generation_uses_validation": False,
            "max_optimized_candidates_per_direction": max_optimized_candidates_per_direction,
            "signal_on_close_fill_next_open": True, "costs_included": True,
            "underpowered_p_value_placeholder": 1.0,
            "p1_placeholder_is_not_a_measured_p_value": True,
            "block_length_sensitivity_analysis_required": True,
            "independent_final_holdout_required": True,
            "walk_forward_is_not_strategy_approval": True,
            "strategy_approval": "NOT_APPROVED",
        },
        "safety": {
            "lookahead_used_for_rule_generation": False,
            "trades_crossing_formation_validation_boundary": False,
            "validation_used_for_optimization": False,
            "capital_or_position_sizing_used": False,
            "broker_or_live_trading_accessed": False,
            "strategy_approval": "NOT_APPROVED",
        },
    }
