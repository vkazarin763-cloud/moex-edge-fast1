"""End-to-end formation/validation loop for autonomous hypothesis research.

This module coordinates existing primitives. It is research-only: candidate
rules are generated on formation data, evaluated once on a later validation
window, corrected as one registered family, and never approved for trading.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .bootstrap import moving_block_bootstrap_mean_test
from .discovery import generate_hypotheses
from .execution import evaluate_hypothesis
from .multiple_testing import holm_bonferroni


class PipelineInputError(ValueError):
    """Invalid chronological split or research-pipeline configuration."""


def run_research_pipeline(
    bars: Sequence[Mapping[str, Any]],
    feature_panel: Mapping[str, Sequence[float | None]],
    exit_hypothesis: Mapping[str, Any],
    *,
    formation_end: int,
    max_features: int = 12,
    max_hypotheses: int = 200,
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
    """Generate rules on [0, formation_end), evaluate on [formation_end, n).

    Feature values may be calculated over the full series only when each row
    is causal (current/past data). The exit rule is caller-supplied and must
    be fixed before validation; a LONG/SHORT mapping may provide distinct
    predeclared exits. This pipeline never searches for an exit on validation
    outcomes. Validation trades cannot cross the split because the
    execution simulator receives only validation bars and feature rows.
    """
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
    if not isinstance(exit_hypothesis, Mapping):
        raise PipelineInputError("a predeclared exit_hypothesis mapping is required")
    if "LONG" in exit_hypothesis or "SHORT" in exit_hypothesis:
        for direction in ("LONG", "SHORT"):
            rule = exit_hypothesis.get(direction)
            if not isinstance(rule, Mapping) or not isinstance(rule.get("conditions"), list) or not rule["conditions"]:
                raise PipelineInputError("directional exit rules must define non-empty LONG and SHORT conditions")
    elif not isinstance(exit_hypothesis.get("conditions"), list) or not exit_hypothesis["conditions"]:
        raise PipelineInputError("exit_hypothesis must contain non-empty conditions")
    if not isinstance(family_id, str) or not family_id.strip():
        raise PipelineInputError("family_id must be a non-empty string")

    # Explicitly generate on the formation prefix, not on the validation tail.
    formation_panel = {name: list(values[:formation_end]) for name, values in feature_panel.items()}
    discovery = generate_hypotheses(
        formation_panel,
        formation_indices=list(range(formation_end)),
        max_features=max_features,
        max_hypotheses=max_hypotheses,
        min_observations=min_formation_observations,
    )
    hypotheses = discovery["hypotheses"]
    if not hypotheses:
        return {
            "status": "NO_CANDIDATES",
            "discovery": discovery,
            "family": {"family_id": family_id, "family_size": 0},
            "results": [],
            "safety": {
                "formation_precedes_validation": True,
                "validation_used_for_generation": False,
                "strategy_approval": "NOT_APPROVED",
            },
        }

    validation_bars = list(bars[formation_end:])
    validation_panel = {name: list(values[formation_end:]) for name, values in feature_panel.items()}
    # A p=1 placeholder retains underpowered hypotheses in the full Holm
    # family. It is not reported as a measured p-value and cannot be promoted.
    family_p_values: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        execution = evaluate_hypothesis(
            validation_bars,
            validation_panel,
            hypothesis,
            (exit_hypothesis[hypothesis["direction"]]
             if "LONG" in exit_hypothesis or "SHORT" in exit_hypothesis
             else exit_hypothesis),
            commission_rate=commission_rate,
            slippage_rate=slippage_rate,
        )
        returns = [trade["net_return"] for trade in execution["trades"]]
        inference = None
        if len(returns) >= min_trades_for_inference and block_length <= len(returns) // 2:
            inference = moving_block_bootstrap_mean_test(
                returns,
                block_length=block_length,
                resamples=resamples,
                alpha=alpha,
                seed=seed,
            )
            family_p_values[hypothesis["id"]] = inference["two_sided_p_value"]
            inference_status = "TESTED"
        else:
            family_p_values[hypothesis["id"]] = 1.0
            inference_status = "INSUFFICIENT_DATA"
        rows.append({
            "hypothesis": hypothesis,
            "execution": execution,
            "inference": inference,
            "inference_status": inference_status,
            "closed_trade_count": len(returns),
            "candidate_for_walk_forward": False,
            "approval_status": "NOT_APPROVED",
        })

    correction = holm_bonferroni(family_p_values, alpha=alpha, family_id=family_id)
    corrected = {item["hypothesis_id"]: item for item in correction["results"]}
    for row in rows:
        adjusted = corrected[row["hypothesis"]["id"]]
        row["multiple_testing"] = adjusted
        ci = row["inference"]["confidence_interval"] if row["inference"] else None
        row["candidate_for_walk_forward"] = bool(
            row["inference_status"] == "TESTED"
            and adjusted["reject_null"]
            and ci is not None
            and ci["lower"] > 0.0
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
            "formation_start_index": 0,
            "formation_end_exclusive": formation_end,
            "validation_start_index": formation_end,
            "validation_end_exclusive": n,
            "validation_bars": len(validation_bars),
        },
        "discovery": discovery,
        "family": {
            "family_id": family_id,
            "family_size_generated": len(hypotheses),
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
            "exit_rule_predeclared_by_caller": True,
            "entry_thresholds_fit_on_formation_only": True,
            "validation_used_for_hypothesis_generation": False,
            "validation_used_for_statistical_evaluation_only": True,
            "signal_on_close_fill_next_open": True,
            "costs_included": True,
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
            "capital_or_position_sizing_used": False,
            "broker_or_live_trading_accessed": False,
            "strategy_approval": "NOT_APPROVED",
        },
    }
