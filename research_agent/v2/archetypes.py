"""Archetype-aware hypothesis generation from causal feature panels.

The generator creates bounded, formation-only rule hypotheses across distinct
market behaviours. Archetype labels describe the intended pattern family;
they are not claims that a rule is profitable or economically validated.
"""
from __future__ import annotations

import hashlib
import json
import math
from itertools import combinations
from typing import Mapping, Sequence


class ArchetypeInputError(ValueError):
    """Invalid input to archetype discovery."""


ARCHETYPES = {
    "TREND_CONTINUATION": ("return_20", "trend_efficiency", "xs_relative_return_20"),
    "BREAKOUT_EXPANSION": ("range_vs_prior_mean", "candle_range_pct", "relative_volume", "return_5"),
    "PULLBACK": ("return_5", "return_20", "close_location", "lower_wick_fraction"),
    "MEAN_REVERSION": ("return_1", "return_5", "upper_wick_fraction", "lower_wick_fraction"),
    "VOLATILITY_REGIME": ("realized_volatility", "range_vs_prior_mean", "relative_volume", "market_dispersion_20"),
    "MARKET_REGIME": ("market_median_return_20", "market_breadth_positive_20", "xs_relative_return_20"),
}


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] if lo == hi else ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def _id(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "HYP-ARCH-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def generate_archetype_hypotheses(
    feature_panel: Mapping[str, Sequence[float | None]],
    *,
    formation_indices: Sequence[int],
    max_hypotheses: int = 100,
    min_observations: int = 20,
    archetypes: Mapping[str, Sequence[str]] = ARCHETYPES,
) -> dict:
    """Generate formation-only one/two-feature rules for six archetype families.

    Thresholds are fitted only on formation_indices. Candidate allocation is
    round-robin across archetypes, directions and ALL/ANY logic, not ranked by
    outcomes. The function deliberately accepts no prices or returns.
    """
    if not isinstance(feature_panel, Mapping) or not feature_panel:
        raise ArchetypeInputError("feature_panel must be a non-empty mapping")
    if not isinstance(formation_indices, Sequence) or isinstance(formation_indices, (str, bytes)) or not formation_indices:
        raise ArchetypeInputError("formation_indices must be a non-empty sequence")
    if isinstance(max_hypotheses, bool) or not isinstance(max_hypotheses, int) or max_hypotheses < 0:
        raise ArchetypeInputError("max_hypotheses must be a non-negative integer")
    if isinstance(min_observations, bool) or not isinstance(min_observations, int) or min_observations < 2:
        raise ArchetypeInputError("min_observations must be >= 2")
    row_count = len(next(iter(feature_panel.values())))
    if any(not isinstance(name, str) or len(values) != row_count for name, values in feature_panel.items()):
        raise ArchetypeInputError("feature names and aligned series are required")
    indices = list(formation_indices)
    if any(isinstance(i, bool) or not isinstance(i, int) or i < 0 or i >= row_count for i in indices):
        raise ArchetypeInputError("formation index outside feature panel")
    if len(set(indices)) != len(indices):
        raise ArchetypeInputError("formation indices must be unique")

    thresholds = {}
    eligible = {}
    for family, names in sorted(archetypes.items()):
        available = []
        for name in names:
            if name not in feature_panel:
                continue
            values = []
            for i in indices:
                value = feature_panel[name][i]
                if value is not None:
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                        raise ArchetypeInputError(f"invalid value in {name}")
                    values.append(float(value))
            if len(values) >= min_observations:
                qs = [(q, _quantile(values, q)) for q in (0.25, 0.50, 0.75)]
                unique = []
                for item in qs:
                    if item[1] not in [x[1] for x in unique]:
                        unique.append(item)
                thresholds[name] = unique
                available.append(name)
        if available:
            eligible[family] = available

    buckets = {}
    for family, names in eligible.items():
        # Include single-feature rules and two-feature interactions.
        feature_sets = [(name,) for name in names] + list(combinations(names, 2))
        for feature_set in feature_sets:
            choices = []
            for name in feature_set:
                choices.append([
                    {"feature": name, "operator": op, "threshold": value,
                     "threshold_quantile": q}
                    for q, value in thresholds[name]
                    for op in (">=", "<=")
                ])
            from itertools import product
            for conditions in product(*choices):
                for direction in ("LONG", "SHORT"):
                    for mode in ("ALL", "ANY"):
                        payload = {
                            "direction": direction, "conditions": list(conditions),
                            "combination": mode, "version": 1,
                            "archetype": family, "generation": "ARCHETYPE",
                        }
                        candidate = {"id": _id(payload), **payload}
                        buckets.setdefault((family, direction, mode), []).append(candidate)

    for bucket in buckets.values():
        bucket.sort(key=lambda item: item["id"])
    keys = sorted(buckets)
    selected = []
    while len(selected) < max_hypotheses and any(buckets[key] for key in keys):
        for key in keys:
            if buckets[key] and len(selected) < max_hypotheses:
                selected.append(buckets[key].pop(0))

    counts = {family: sum(x["archetype"] == family for x in selected) for family in ARCHETYPES}
    return {
        "status": "GENERATED" if selected else "NO_ELIGIBLE_ARCHETYPES",
        "generator": "formation_only_archetype_round_robin_v1",
        "eligible_archetypes": list(eligible),
        "selected_by_archetype": counts,
        "selected_by_direction_and_logic": {
            f"{direction}_{mode}": sum(x["direction"] == direction and x["combination"] == mode for x in selected)
            for direction in ("LONG", "SHORT") for mode in ("ALL", "ANY")
        },
        "hypothesis_count": len(selected),
        "hypotheses": selected,
        "safety": {
            "thresholds_fit_on_formation_indices_only": True,
            "validation_rows_used": False,
            "forward_returns_used": False,
            "outcome_based_ranking_used": False,
        },
    }
