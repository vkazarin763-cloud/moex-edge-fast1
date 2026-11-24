"""Holm step-down correction for a complete, pre-declared hypothesis family."""
from __future__ import annotations
import math
from collections.abc import Mapping
from typing import Any

class MultipleTestingInputError(ValueError):
    """Invalid hypothesis family or p-value input."""

def holm_bonferroni(p_values: Mapping[str, float], *, alpha: float = 0.05, family_id: str) -> dict[str, Any]:
    """Adjust externally computed p-values using Holm's step-down method.

    Supply every hypothesis tested in the pre-declared family, including
    unsuccessful candidates. This function does not calculate p-values.
    Holm controls family-wise error under arbitrary dependence only when each
    marginal p-value is valid. It cannot correct unregistered research or
    invalid tests; independent out-of-sample validation remains mandatory.
    """
    if not isinstance(family_id, str) or not family_id.strip():
        raise MultipleTestingInputError("family_id must be a non-empty string")
    if not isinstance(p_values, Mapping) or not p_values:
        raise MultipleTestingInputError("p_values must be a non-empty mapping")
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
        raise MultipleTestingInputError("alpha must be numeric")
    alpha = float(alpha)
    if not math.isfinite(alpha) or not 0.0 < alpha < 1.0:
        raise MultipleTestingInputError("alpha must be finite and between 0 and 1")

    items = []
    seen = set()
    for order, (hypothesis_id, raw_p) in enumerate(p_values.items()):
        if not isinstance(hypothesis_id, str) or not hypothesis_id.strip():
            raise MultipleTestingInputError("hypothesis IDs must be non-empty strings")
        if hypothesis_id in seen:
            raise MultipleTestingInputError("hypothesis IDs must be unique")
        seen.add(hypothesis_id)
        if isinstance(raw_p, bool) or not isinstance(raw_p, (int, float)):
            raise MultipleTestingInputError(f"p-value for {hypothesis_id} must be numeric")
        p_value = float(raw_p)
        if not math.isfinite(p_value) or not 0.0 <= p_value <= 1.0:
            raise MultipleTestingInputError(f"p-value for {hypothesis_id} must be within [0, 1]")
        items.append((hypothesis_id, p_value, order))

    ranked = sorted(items, key=lambda item: (item[1], item[2]))
    size = len(ranked)
    adjusted_by_id = {}
    running_max = 0.0
    for rank, (hypothesis_id, p_value, _) in enumerate(ranked):
        running_max = max(running_max, min(1.0, (size - rank) * p_value))
        adjusted_by_id[hypothesis_id] = running_max

    results = []
    for hypothesis_id, p_value, _ in items:
        adjusted = adjusted_by_id[hypothesis_id]
        reject = adjusted <= alpha
        results.append({
            "hypothesis_id": hypothesis_id,
            "raw_p_value": p_value,
            "holm_adjusted_p_value": adjusted,
            "reject_null": reject,
            "status": "REJECT_NULL_AFTER_HOLM" if reject else "NOT_SIGNIFICANT_AFTER_HOLM",
        })
    return {
        "status": "CORRECTED",
        "method": "Holm-Bonferroni step-down",
        "family_id": family_id,
        "family_size": size,
        "alpha": alpha,
        "results": results,
        "safety": {
            "p_values_computed_here": False,
            "complete_family_supplied_by_caller": True,
            "controls_family_wise_error_under_arbitrary_dependence": True,
            "valid_marginal_p_values_required": True,
            "out_of_sample_validation_still_required": True,
            "strategy_approval": "NOT_APPROVED",
        },
    }
