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

    # Build the full single-feature space first, then sample it evenly across
    # quantiles and directions. The previous nested loop exhausted its budget
    # on the lowest quantiles and alphabetically early features.
    hypotheses = []
    seen_ids = set()
    single_buckets: dict[tuple[int, str], list[dict]] = {}
    for q_index in range(max((len(v) for v in threshold_map.values()), default=0)):
        for name in eligible_features:
            if q_index >= len(threshold_map[name]):
                continue
            item = threshold_map[name][q_index]
            for operator in (">=", "<="):
                for direction in ("LONG", "SHORT"):
                    payload = {
                        "direction": direction,
                        "conditions": [{
                            "feature": name, "operator": operator,
                            "threshold": item["value"],
                            "threshold_quantile": item["quantile"],
                        }],
                        "combination": "ALL", "version": 4,
                    }
                    hypothesis_id = _hypothesis_id(payload)
                    single_buckets.setdefault((q_index, direction), []).append(
                        {"id": hypothesis_id, **payload}
                    )

    # Reserve roughly two thirds for singles and one third for interactions.
    # Round-robin buckets guarantee that both directions and all available
    # quantiles are represented before any one bucket consumes the budget.
    single_budget = max(1, (max_hypotheses + 1) // 2)
    bucket_keys = [
        (q_index, direction)
        for q_index in range(max((len(v) for v in threshold_map.values()), default=0))
        for direction in ("LONG", "SHORT")
    ]
    while len(hypotheses) < single_budget and any(single_buckets.get(k) for k in bucket_keys):
        for key in bucket_keys:
            bucket = single_buckets.get(key, [])
            if bucket and len(hypotheses) < single_budget:
                item = bucket.pop(0)
                if item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    hypotheses.append(item)

    # Generate two-feature interactions with independently varied quantiles.
    # A stable hash ordering samples broadly across feature pairs, thresholds,
    # operators and directions without using outcomes or runtime randomness.
    interaction_buckets: dict[tuple[str, str], list[dict]] = {}
    feature_pairs = []
    pair_seen = set()
    # Start with pairs spread across opposite ends of the feature list, then
    # cover the remaining combinations. This avoids early features dominating.
    for offset in range(len(eligible_features) // 2):
        left, right = eligible_features[offset], eligible_features[-1 - offset]
        feature_pairs.append((left, right))
        pair_seen.add(frozenset((left, right)))
    for left, right in combinations(eligible_features, 2):
        if frozenset((left, right)) not in pair_seen:
            feature_pairs.append((left, right))
    for left, right in feature_pairs:
        bucket = []
        for left_item in threshold_map[left]:
            for right_item in threshold_map[right]:
                for left_op in (">=", "<="):
                    for right_op in (">=", "<="):
                        conditions = [
                            {"feature": left, "operator": left_op,
                             "threshold": left_item["value"],
                             "threshold_quantile": left_item["quantile"]},
                            {"feature": right, "operator": right_op,
                             "threshold": right_item["value"],
                             "threshold_quantile": right_item["quantile"]},
                        ]
                        for direction in ("LONG", "SHORT"):
                            payload = {
                                "direction": direction, "conditions": conditions,
                                "combination": "ALL", "version": 4,
                            }
                            hypothesis_id = _hypothesis_id(payload)
                            bucket.append({"id": hypothesis_id, **payload})
        bucket.sort(key=lambda item: item["id"])
        interaction_buckets[(left, right)] = bucket

    # Round-robin over feature pairs so a small candidate cap still samples
    # the feature space instead of concentrating on a few pairs.
    pair_keys = list(interaction_buckets)
    while len(hypotheses) < max_hypotheses and any(interaction_buckets[k] for k in pair_keys):
        for key in pair_keys:
            bucket = interaction_buckets[key]
            if bucket and len(hypotheses) < max_hypotheses:
                item = bucket.pop(0)
                if item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    hypotheses.append(item)

    truncated = len(hypotheses) >= max_hypotheses

    return {
        "status": "GENERATED" if hypotheses else "NO_ELIGIBLE_FEATURES",
        "generator": "balanced_single_and_pair_quantile_rules_v4",
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
    """Generate two-feature ALL/ANY exit alternatives from formation data only.

    Each exit combines comparisons on distinct features. Thresholds are
    estimated only on formation_indices; deterministic round-robin selection
    retains both logic families when the requested cap permits. No outcomes,
    trade returns, or validation rows are accepted.
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
        if len(values) >= min_observations:
            eligible.append((name, values))
    preferred = [item for item in eligible if item[0] not in entry_features]
    pool = preferred or eligible
    entry_id = str(entry_hypothesis.get("id", "entry"))
    if pool:
        offset = int(hashlib.sha256(entry_id.encode("utf-8")).hexdigest()[:8], 16) % len(pool)
        pool = pool[offset:] + pool[:offset]

    buckets: dict[str, list[dict]] = {"ALL": [], "ANY": []}
    for (left_name, left_values), (right_name, right_values) in combinations(pool, 2):
        for left_q in (0.40, 0.60):
            for right_q in (0.40, 0.60):
                left_threshold = _quantile(left_values, left_q)
                right_threshold = _quantile(right_values, right_q)
                for left_op in ("<=", ">="):
                    for right_op in ("<=", ">="):
                        conditions = [
                            {"feature": left_name, "operator": left_op,
                             "threshold": left_threshold, "threshold_quantile": left_q},
                            {"feature": right_name, "operator": right_op,
                             "threshold": right_threshold, "threshold_quantile": right_q},
                        ]
                        for mode in ("ALL", "ANY"):
                            payload = {
                                "direction": entry_hypothesis.get("direction"),
                                "conditions": conditions, "combination": mode,
                                "role": "EXIT", "version": 2,
                            }
                            exit_id = _hypothesis_id(payload)
                            buckets[mode].append({"id": exit_id, **payload})

    if not buckets["ALL"] and not buckets["ANY"] and pool:
        # A single eligible feature cannot form a meaningful two-feature rule.
        name, values = pool[0]
        for q, operator in ((0.40, "<="), (0.60, ">=")):
            payload = {
                "direction": entry_hypothesis.get("direction"),
                "conditions": [{"feature": name, "operator": operator,
                                "threshold": _quantile(values, q),
                                "threshold_quantile": q}],
                "combination": "ALL", "role": "EXIT", "version": 2,
            }
            exit_id = _hypothesis_id(payload)
            buckets["ALL"].append({"id": exit_id, **payload})

    for mode in buckets:
        buckets[mode].sort(key=lambda item: hashlib.sha256(item["id"].encode("utf-8")).hexdigest())
    exits = []
    while len(exits) < max_exit_hypotheses and any(buckets.values()):
        added = False
        for mode in ("ALL", "ANY"):
            if buckets[mode] and len(exits) < max_exit_hypotheses:
                exits.append(buckets[mode].pop(0))
                added = True
        if not added:
            break
    return {
        "status": "GENERATED" if exits else "NO_ELIGIBLE_EXIT_FEATURES",
        "generator": "formation_only_two_feature_all_any_exit_rules_v2",
        "combination_modes": sorted({item["combination"] for item in exits}),
        "hypothesis_count": len(exits),
        "hypotheses": exits,
        "safety": {
            "forward_returns_used": False,
            "thresholds_fit_on_formation_indices_only": True,
            "validation_used_for_exit_generation": False,
            "requires_global_multiple_testing_and_unseen_evaluation": True,
        },
    }
