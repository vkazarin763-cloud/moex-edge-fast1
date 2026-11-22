"""Data-driven, deterministic generation of research hypotheses.

This is a discovery primitive, not a backtester or a strategy approval system.
It learns feature thresholds from an explicitly supplied formation window only.
It never reads forward returns, broker data, or production scanner state.
"""
from __future__ import annotations

import hashlib
import json
import math
from itertools import combinations
from typing import Mapping, Sequence

DEFAULT_QUANTILES = (0.20, 0.40, 0.60, 0.80)
DEFAULT_MAX_FEATURES = 12
DEFAULT_MAX_HYPOTHESES = 2_000
DEFAULT_MIN_OBSERVATIONS = 20


class DiscoveryInputError(ValueError):
    """Raised when the feature panel or formation window is invalid."""


def _quantile(values: list[float], q: float) -> float:
    """Linear-interpolated quantile, implemented without third-party deps."""
    ordered = sorted(values)
    if not ordered:
        raise DiscoveryInputError("cannot calculate a quantile from no values")
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _validate_panel(
    feature_panel: Mapping[str, Sequence[float | None]],
) -> tuple[int, dict[str, list[float | None]]]:
    if not isinstance(feature_panel, Mapping) or not feature_panel:
        raise DiscoveryInputError("feature_panel must be a non-empty mapping")
    normalized: dict[str, list[float | None]] = {}
    row_count: int | None = None
    for name, series in feature_panel.items():
        if not isinstance(name, str) or not name.strip():
            raise DiscoveryInputError("feature names must be non-empty strings")
        if isinstance(series, (str, bytes)) or not isinstance(series, Sequence):
            raise DiscoveryInputError(f"feature {name!r} must be a sequence")
        values: list[float | None] = []
        for index, value in enumerate(series):
            if value is None:
                values.append(None)
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise DiscoveryInputError(
                    f"feature {name!r} row {index} is not numeric or None"
                )
            number = float(value)
            if not math.isfinite(number):
                raise DiscoveryInputError(
                    f"feature {name!r} row {index} is non-finite"
                )
            values.append(number)
        if row_count is None:
            row_count = len(values)
        elif len(values) != row_count:
            raise DiscoveryInputError("all feature series must have equal length")
        normalized[name] = values
    if not row_count:
        raise DiscoveryInputError("feature series must not be empty")
    return row_count, normalized


def _validate_indices(indices: Sequence[int], row_count: int) -> list[int]:
    if isinstance(indices, (str, bytes)) or not isinstance(indices, Sequence) or not indices:
        raise DiscoveryInputError("formation_indices must be a non-empty sequence")
    result: list[int] = []
    seen: set[int] = set()
    for index in indices:
        if isinstance(index, bool) or not isinstance(index, int):
            raise DiscoveryInputError("formation indices must be integers")
        if index < 0 or index >= row_count:
            raise DiscoveryInputError("formation index is outside the feature panel")
        if index in seen:
            raise DiscoveryInputError("formation indices must be unique")
        seen.add(index)
        result.append(index)
    return result


def _hypothesis_id(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "HYP-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def generate_hypotheses(
    feature_panel: Mapping[str, Sequence[float | None]],
    *,
    formation_indices: Sequence[int],
    quantiles: Sequence[float] = DEFAULT_QUANTILES,
    max_features: int = DEFAULT_MAX_FEATURES,
    max_hypotheses: int = DEFAULT_MAX_HYPOTHESES,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
) -> dict:
    """Generate directional single-feature and two-feature rule hypotheses.

    Thresholds are estimated only from formation_indices. The returned rules
    can later be applied to unseen rows. Forward returns are intentionally not
    accepted by this API, preventing outcome-guided hypothesis construction.

    Each rule is a conjunction of one or two feature comparisons. Both LONG
    and SHORT variants are emitted. This creates a broad, data-driven search
    space without hard-coding indicator names or market-specific thresholds.
    """
    row_count, panel = _validate_panel(feature_panel)
    indices = _validate_indices(formation_indices, row_count)

    if isinstance(max_features, bool) or not isinstance(max_features, int) or max_features < 1:
        raise DiscoveryInputError("max_features must be a positive integer")
    if isinstance(max_hypotheses, bool) or not isinstance(max_hypotheses, int) or max_hypotheses < 1:
        raise DiscoveryInputError("max_hypotheses must be a positive integer")
    if isinstance(min_observations, bool) or not isinstance(min_observations, int) or min_observations < 2:
        raise DiscoveryInputError("min_observations must be an integer >= 2")
    if isinstance(quantiles, (str, bytes)) or not isinstance(quantiles, Sequence) or not quantiles:
        raise DiscoveryInputError("quantiles must be a non-empty sequence")
    qs = []
    for q in quantiles:
        if isinstance(q, bool) or not isinstance(q, (int, float)) or not 0.0 < float(q) < 1.0:
            raise DiscoveryInputError("each quantile must be strictly between 0 and 1")
        qs.append(float(q))
    qs = sorted(set(qs))

    eligible_features = []
    threshold_map: dict[str, list[dict]] = {}
    for name in sorted(panel)[:max_features]:
        observed = [panel[name][i] for i in indices if panel[name][i] is not None]
        values = [float(value) for value in observed if value is not None]
        if len(values) < min_observations:
            continue
        thresholds = []
        seen_thresholds = set()
        for q in qs:
            value = _quantile(values, q)
            if value in seen_thresholds:
                continue
            seen_thresholds.add(value)
            thresholds.append({"quantile": q, "value": value})
        if thresholds:
            eligible_features.append(name)
            threshold_map[name] = thresholds

    # Reserve part of the fixed budget for interactions. Without this split,
    # a 20-hypothesis cap is consumed by single-feature rules and conjunctions
    # are never explored.
    hypotheses = []
    seen_ids = set()
    single_budget = max(1, (max_hypotheses * 3) // 4)
    for q_index in range(max((len(v) for v in threshold_map.values()), default=0)):
        for operator in (">=", "<="):
            for name in eligible_features:
                if q_index >= len(threshold_map[name]):
                    continue
                item = threshold_map[name][q_index]
                for direction in ("LONG", "SHORT"):
                    payload = {
                        "direction": direction,
                        "conditions": [{
                            "feature": name, "operator": operator,
                            "threshold": item["value"],
                            "threshold_quantile": item["quantile"],
                        }],
                        "combination": "ALL", "version": 3,
                    }
                    hypothesis_id = _hypothesis_id(payload)
                    if hypothesis_id in seen_ids:
                        continue
                    if len(hypotheses) >= single_budget:
                        break
                    seen_ids.add(hypothesis_id)
                    hypotheses.append({"id": hypothesis_id, **payload})
                if len(hypotheses) >= single_budget:
                    break
            if len(hypotheses) >= single_budget:
                break
        if len(hypotheses) >= single_budget:
            break

    # Fill the remaining budget with two-feature interactions. Rotate through
    # distinct feature pairs before moving to further quantile combinations.
    pair_specs = []
    for left, right in combinations(eligible_features, 2):
        for q_index in range(min(len(threshold_map[left]), len(threshold_map[right]))):
            left_item, right_item = threshold_map[left][q_index], threshold_map[right][q_index]
            for left_op, right_op in ((">=", "<="), ("<=", ">=")):
                pair_specs.append([
                    {"feature": left, "operator": left_op,
                     "threshold": left_item["value"],
                     "threshold_quantile": left_item["quantile"]},
                    {"feature": right, "operator": right_op,
                     "threshold": right_item["value"],
                     "threshold_quantile": right_item["quantile"]},
                ])
    for conditions in pair_specs:
        for direction in ("LONG", "SHORT"):
            payload = {"direction": direction, "conditions": conditions,
                       "combination": "ALL", "version": 3}
            hypothesis_id = _hypothesis_id(payload)
            if hypothesis_id in seen_ids:
                continue
            if len(hypotheses) >= max_hypotheses:
                break
            seen_ids.add(hypothesis_id)
            hypotheses.append({"id": hypothesis_id, **payload})
        if len(hypotheses) >= max_hypotheses:
            break
    truncated = len(hypotheses) >= max_hypotheses

    return {
        "status": "GENERATED" if hypotheses else "NO_ELIGIBLE_FEATURES",
        "generator": "balanced_single_and_pair_quantile_rules_v3",
        "formation_indices": list(indices),
        "formation_observations": len(indices),
        "eligible_features": eligible_features,
        "feature_thresholds": threshold_map,
        "hypothesis_count": len(hypotheses),
        "truncated": truncated,
        "hypotheses": hypotheses,
        "safety": {
            "forward_returns_used": False,
            "thresholds_fit_on_formation_indices_only": True,
            "requires_separate_unseen_evaluation": True,
            "approval_status": "NOT_EVALUATED",
        },
    }


def matches_hypothesis(
    hypothesis: Mapping,
    feature_panel: Mapping[str, Sequence[float | None]],
    row_index: int,
) -> bool:
    """Apply a generated conjunction to one row; missing values fail closed."""
    row_count, panel = _validate_panel(feature_panel)
    if isinstance(row_index, bool) or not isinstance(row_index, int) or not 0 <= row_index < row_count:
        raise DiscoveryInputError("row_index is outside the feature panel")
    if not isinstance(hypothesis, Mapping) or not isinstance(hypothesis.get("conditions"), list):
        raise DiscoveryInputError("hypothesis must contain a conditions list")
    conditions = hypothesis["conditions"]
    if not conditions:
        raise DiscoveryInputError("hypothesis conditions must not be empty")
    for condition in conditions:
        if not isinstance(condition, Mapping):
            raise DiscoveryInputError("each condition must be a mapping")
        feature = condition.get("feature")
        operator = condition.get("operator")
        threshold = condition.get("threshold")
        if feature not in panel or operator not in (">=", "<="):
            raise DiscoveryInputError("hypothesis references an unknown feature or operator")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(float(threshold)):
            raise DiscoveryInputError("condition threshold must be finite numeric")
        value = panel[feature][row_index]
        if value is None:
            return False
        if operator == ">=" and value < threshold:
            return False
        if operator == "<=" and value > threshold:
            return False
    return True


def generate_exit_hypotheses(
    feature_panel: Mapping[str, Sequence[float | None]],
    *,
    formation_indices: Sequence[int],
    entry_hypothesis: Mapping,
    max_exit_hypotheses: int = 2,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
) -> dict:
    """Generate outcome-blind exit alternatives using formation data only.

    Exit thresholds are fitted on the same chronological formation prefix as
    entry thresholds. Candidate features are rotated deterministically by
    entry ID so a small cap does not always select the same first columns.
    No trade returns, validation rows, or future outcomes are accepted.
    """
    row_count, panel = _validate_panel(feature_panel)
    indices = _validate_indices(formation_indices, row_count)
    if not isinstance(entry_hypothesis, Mapping):
        raise DiscoveryInputError("entry_hypothesis must be a mapping")
    if isinstance(max_exit_hypotheses, bool) or not isinstance(max_exit_hypotheses, int) or max_exit_hypotheses < 1:
        raise DiscoveryInputError("max_exit_hypotheses must be a positive integer")
    entry_features = {
        condition.get("feature")
        for condition in entry_hypothesis.get("conditions", [])
        if isinstance(condition, Mapping)
    }
    eligible = []
    for name in sorted(panel):
        values = [float(panel[name][i]) for i in indices if panel[name][i] is not None]
        if len(values) < min_observations:
            continue
        eligible.append((name, values))
    if not eligible:
        return {"status": "NO_ELIGIBLE_EXIT_FEATURES", "hypotheses": [],
                "safety": {"forward_returns_used": False,
                           "thresholds_fit_on_formation_indices_only": True}}
    preferred = [item for item in eligible if item[0] not in entry_features]
    pool = preferred or eligible
    entry_id = str(entry_hypothesis.get("id", "entry"))
    offset = int(hashlib.sha256(entry_id.encode("utf-8")).hexdigest()[:8], 16) % len(pool)
    pool = pool[offset:] + pool[:offset]
    exits = []
    for index, (name, values) in enumerate(pool):
        q = 0.40 if index % 2 == 0 else 0.60
        operator = "<=" if index % 2 == 0 else ">="
        threshold = _quantile(values, q)
        payload = {
            "direction": entry_hypothesis.get("direction"),
            "conditions": [{
                "feature": name, "operator": operator,
                "threshold": threshold, "threshold_quantile": q,
            }],
            "combination": "ALL", "role": "EXIT", "version": 1,
        }
        exit_id = _hypothesis_id(payload)
        exits.append({"id": exit_id, **payload})
        if len(exits) >= max_exit_hypotheses:
            break
    return {
        "status": "GENERATED",
        "generator": "formation_only_rotating_exit_rules_v1",
        "hypothesis_count": len(exits),
        "hypotheses": exits,
        "safety": {
            "forward_returns_used": False,
            "thresholds_fit_on_formation_indices_only": True,
            "validation_used_for_exit_generation": False,
            "requires_global_multiple_testing_and_unseen_evaluation": True,
        },
    }
