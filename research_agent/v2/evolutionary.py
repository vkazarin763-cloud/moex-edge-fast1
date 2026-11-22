"""Deterministic mutation/crossover expansion for autonomous rule discovery.

This module creates 3- and 4-condition entry rules with ALL and ANY logic,
using formation-window feature distributions only. It never accepts returns
or validation data. The caller evaluates the resulting population on formation
data and performs the frozen-shortlist/chronological-validation protocol.
"""
from __future__ import annotations

import hashlib
import json
from itertools import combinations, product
from typing import Mapping, Sequence


class EvolutionInputError(ValueError):
    """Invalid input to evolutionary hypothesis expansion."""


def _identifier(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "HYP-EVO-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def expand_hypotheses(
    feature_panel: Mapping[str, Sequence[float | None]],
    *,
    formation_indices: Sequence[int],
    seed_hypotheses: Sequence[Mapping],
    max_hypotheses: int = 200,
    max_conditions: int = 4,
    min_observations: int = 20,
    combination_modes: Sequence[str] = ("ALL", "ANY"),
) -> dict:
    """Mutate and cross seed rules into bounded 3/4-feature rule sets.

    Mutations append a condition on a previously unused feature. Crossovers
    combine disjoint condition sets from same-direction parent rules. Candidate
    ordering is stable and round-robin across LONG/SHORT and ALL/ANY buckets,
    so candidate caps do not silently exclude a logic family.
    """
    if not isinstance(feature_panel, Mapping) or not feature_panel:
        raise EvolutionInputError("feature_panel must be a non-empty mapping")
    if not isinstance(formation_indices, Sequence) or not formation_indices:
        raise EvolutionInputError("formation_indices must be non-empty")
    if isinstance(max_hypotheses, bool) or not isinstance(max_hypotheses, int) or max_hypotheses < 0:
        raise EvolutionInputError("max_hypotheses must be a non-negative integer")
    if isinstance(max_conditions, bool) or not isinstance(max_conditions, int) or not 3 <= max_conditions <= 4:
        raise EvolutionInputError("max_conditions must be 3 or 4")
    if (not isinstance(combination_modes, Sequence) or isinstance(combination_modes, (str, bytes))
            or not combination_modes or any(mode not in ("ALL", "ANY") for mode in combination_modes)):
        raise EvolutionInputError("combination_modes must contain ALL and/or ANY")
    modes = tuple(dict.fromkeys(combination_modes))
    row_count = len(next(iter(feature_panel.values())))
    if any(len(values) != row_count for values in feature_panel.values()):
        raise EvolutionInputError("feature series must be aligned")
    if any(isinstance(i, bool) or not isinstance(i, int) or i < 0 or i >= row_count
           for i in formation_indices):
        raise EvolutionInputError("formation index is outside the panel")

    atoms: dict[str, list[dict]] = {}
    for name in sorted(feature_panel):
        values = [float(feature_panel[name][i]) for i in formation_indices
                  if feature_panel[name][i] is not None]
        if len(values) < min_observations:
            continue
        ordered = sorted(values)
        thresholds = []
        for q in (0.2, 0.4, 0.6, 0.8):
            pos = (len(ordered) - 1) * q
            lower = int(pos)
            upper = min(lower + 1, len(ordered) - 1)
            fraction = pos - lower
            threshold = ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction
            item = (q, threshold)
            if item not in thresholds:
                thresholds.append(item)
        atoms[name] = [
            {"feature": name, "operator": op, "threshold": threshold,
             "threshold_quantile": q}
            for q, threshold in thresholds
            for op in (">=", "<=")
        ]

    parents = []
    for item in seed_hypotheses:
        if not isinstance(item, Mapping) or item.get("direction") not in ("LONG", "SHORT"):
            continue
        conditions = item.get("conditions")
        if isinstance(conditions, list) and 1 <= len(conditions) < max_conditions:
            parents.append(item)
    generated: dict[str, dict] = {}

    # Mutation: add one or two new feature conditions to each parent.
    for parent in parents:
        existing = {c.get("feature") for c in parent["conditions"]}
        eligible = [name for name in sorted(atoms) if name not in existing]
        for add_count in (1, 2):
            target_size = len(parent["conditions"]) + add_count
            if target_size < 3 or target_size > max_conditions:
                continue
            for names in combinations(eligible, add_count):
                choices = [atoms[name] for name in names]
                for atom_combo in product(*choices):
                    conditions = list(parent["conditions"]) + list(atom_combo)
                    for mode in modes:
                        payload = {"direction": parent["direction"], "conditions": conditions,
                                   "combination": mode, "version": 2, "generation": "MUTATION"}
                        candidate_id = _identifier(payload)
                        generated[candidate_id] = {"id": candidate_id, **payload}

    # Crossover: combine disjoint parents of the same direction.
    for left, right in combinations(parents, 2):
        if left["direction"] != right["direction"]:
            continue
        left_conditions, right_conditions = left["conditions"], right["conditions"]
        features_left = {c.get("feature") for c in left_conditions}
        features_right = {c.get("feature") for c in right_conditions}
        if features_left & features_right:
            continue
        conditions = list(left_conditions) + list(right_conditions)
        if 3 <= len(conditions) <= max_conditions:
            for mode in modes:
                payload = {"direction": left["direction"], "conditions": conditions,
                           "combination": mode, "version": 2, "generation": "CROSSOVER"}
                candidate_id = _identifier(payload)
                generated[candidate_id] = {"id": candidate_id, **payload}

    # Round-robin buckets preserve representation across direction and logic.
    buckets: dict[tuple[str, str], list[dict]] = {}
    for item in generated.values():
        key = (item["direction"], item["combination"])
        buckets.setdefault(key, []).append(item)
    for bucket in buckets.values():
        bucket.sort(key=lambda item: hashlib.sha256(item["id"].encode("utf-8")).hexdigest())
    keys = [(direction, mode) for direction in ("LONG", "SHORT") for mode in ("ALL", "ANY")
            if (direction, mode) in buckets]
    selected = []
    while len(selected) < max_hypotheses and any(buckets[key] for key in keys):
        for key in keys:
            if buckets[key] and len(selected) < max_hypotheses:
                selected.append(buckets[key].pop(0))
    return {
        "status": "GENERATED" if selected else "NO_EVOLVED_RULES",
        "generator": "deterministic_mutation_crossover_all_any_v2",
        "combination_modes": list(modes),
        "selected_by_direction_and_logic": {
            f"{direction}_{mode}": sum(item["direction"] == direction and item["combination"] == mode for item in selected)
            for direction in ("LONG", "SHORT") for mode in ("ALL", "ANY")
        },
        "seed_rules": len(parents),
        "mutation_crossover_candidates": len(generated),
        "hypothesis_count": len(selected),
        "max_conditions": max_conditions,
        "hypotheses": selected,
        "safety": {
            "formation_indices_only": True,
            "forward_returns_used": False,
            "validation_rows_used": False,
            "fitness_evaluation_deferred_to_formation_optimizer": True,
        },
    }
