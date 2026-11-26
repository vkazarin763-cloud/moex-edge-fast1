#!/usr/bin/env python3
"""Non-overlapping, per-symbol robustness and cost sensitivity for the frozen TA event study.

Input is the event CSV emitted by run_ta_pattern_event_study.py. That source has
already excluded every bar on/after 2026-11-20 and split corporate-action price
scale discontinuities. This script never loads raw candles or holdout data.
"""
from __future__ import annotations

import json
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd

SOURCE = Path("ta-event-study-report/events.csv")
OUT = Path("ta-event-study-report")
BASE_ROUND_TRIP_COST = 0.0016
ROUND_TRIP_COSTS = (0.0016, 0.0032, 0.0064, 0.0100)


def equal_symbol_summary(frame: pd.DataFrame, value_col: str, baseline_col: str) -> pd.DataFrame:
    """First average within symbol, then weight every symbol equally."""
    keys = ["period", "feature", "metric", "timeframe", "horizon_bars"]
    per_symbol = (
        frame.groupby(keys + ["symbol"], dropna=False)
        .agg(
            observations=(value_col, "size"),
            mean_value=(value_col, "mean"),
            mean_baseline=(baseline_col, "mean"),
            win_rate=("win_at_cost", "mean") if "win_at_cost" in frame else ("event_value", lambda x: np.nan),
        )
        .reset_index()
    )
    per_symbol["mean_excess"] = per_symbol["mean_value"] - per_symbol["mean_baseline"]
    result = (
        per_symbol.groupby(keys, dropna=False)
        .agg(
            symbols=("symbol", "nunique"),
            events=("observations", "sum"),
            equal_symbol_mean_value=("mean_value", "mean"),
            equal_symbol_mean_baseline=("mean_baseline", "mean"),
            equal_symbol_mean_excess=("mean_excess", "mean"),
            equal_symbol_win_rate=("win_rate", "mean"),
            positive_excess_symbols=("mean_excess", lambda x: int((x > 0).sum())),
            pct_symbols_positive_excess=("mean_excess", lambda x: float((x > 0).mean())),
        )
        .reset_index()
    )
    return result


def one_sided_sign_p(positive: int, total: int) -> float:
    """Exact one-sided sign-test p-value under a 50/50 null."""
    if total <= 0:
        return float("nan")
    return float(sum(comb(total, k) for k in range(positive, total + 1)) / (2 ** total))


def benjamini_hochberg(values: pd.Series) -> pd.Series:
    """Benjamini-Hochberg adjusted p-values, preserving original row order."""
    p = values.to_numpy(dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order] * n / np.arange(1, n + 1)
    adjusted_sorted = np.minimum.accumulate(ranked[::-1])[::-1]
    adjusted = np.empty(n, dtype=float)
    adjusted[order] = np.minimum(adjusted_sorted, 1.0)
    return pd.Series(adjusted, index=values.index)


def main() -> int:
    if not SOURCE.exists():
        raise FileNotFoundError(SOURCE)
    df = pd.read_csv(SOURCE)
    required = {
        "symbol", "timeframe", "period", "feature", "label", "direction",
        "metric", "horizon_bars", "signal_timestamp", "entry_timestamp",
        "exit_timestamp", "event_value", "matched_baseline", "excess_vs_baseline",
    }
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"Event CSV is missing columns: {sorted(missing)}")
    if df.empty:
        raise RuntimeError("Event CSV is empty")

    input_event_count = len(df)
    for col in ("signal_timestamp", "entry_timestamp", "exit_timestamp"):
        df[col + "_dt"] = pd.to_datetime(df[col], format="mixed", utc=True, errors="raise")

    # Family-level selection: same symbol/timeframe/period/feature/metric/horizon.
    # Multiple labels on the same bar with the same direction are one observation;
    # conflicting directions on the same bar are discarded as ambiguous.
    family_keys = ["symbol", "timeframe", "period", "feature", "metric", "horizon_bars"]
    same_bar_keys = family_keys + ["signal_timestamp", "entry_timestamp", "exit_timestamp"]
    direction_counts = df.groupby(same_bar_keys, dropna=False)["direction"].nunique()
    ambiguous = set(direction_counts[direction_counts > 1].index.tolist())
    if ambiguous:
        idx = pd.MultiIndex.from_frame(df[same_bar_keys])
        df = df.loc[~idx.isin(ambiguous)].copy()
    ambiguous_rows_excluded = input_event_count - len(df)
    rows_before_deduplication = len(df)
    df = df.drop_duplicates(subset=same_bar_keys + ["direction"], keep="first")
    same_bar_duplicates_collapsed = rows_before_deduplication - len(df)
    ordered = df.sort_values(
        family_keys + ["entry_timestamp_dt", "signal_timestamp_dt", "exit_timestamp_dt"],
        kind="mergesort",
    ).reset_index(drop=True)

    selected_positions: list[int] = []
    for _, positions in ordered.groupby(family_keys, sort=False, dropna=False).indices.items():
        last_exit = None
        for pos in positions:
            row = ordered.iloc[pos]
            if last_exit is None or row["entry_timestamp_dt"] > last_exit:
                selected_positions.append(pos)
                last_exit = row["exit_timestamp_dt"]
    nonoverlap = ordered.iloc[selected_positions].copy()
    if nonoverlap.empty:
        raise RuntimeError("No non-overlapping observations selected")

    directional = nonoverlap[nonoverlap["metric"] == "DIRECTIONAL_NET_RETURN"].copy()
    neutral = nonoverlap[nonoverlap["metric"] == "ABSOLUTE_MOVE"].copy()

    # Cost sensitivity uses the stored 0.16% round-trip net result to recover
    # direction-adjusted gross return; baseline is adjusted by the same cost.
    cost_tables = []
    for cost in ROUND_TRIP_COSTS:
        sample = directional.copy()
        gross = sample["event_value"] + BASE_ROUND_TRIP_COST
        gross_baseline = sample["matched_baseline"] + BASE_ROUND_TRIP_COST
        sample["net_at_cost"] = gross - cost
        sample["baseline_at_cost"] = gross_baseline - cost
        sample["win_at_cost"] = sample["net_at_cost"] > 0
        cost_table = equal_symbol_summary(sample, "net_at_cost", "baseline_at_cost")
        cost_table["round_trip_cost"] = cost
        cost_tables.append(cost_table)
    cost_sensitivity = pd.concat(cost_tables, ignore_index=True)

    if not directional.empty:
        directional["win_at_cost"] = directional["event_value"] > 0
        nonoverlap_directional = equal_symbol_summary(
            directional, "event_value", "matched_baseline"
        )
    else:
        nonoverlap_directional = pd.DataFrame()

    if not neutral.empty:
        neutral["win_at_cost"] = np.nan
        nonoverlap_neutral = equal_symbol_summary(
            neutral, "event_value", "matched_baseline"
        )
    else:
        nonoverlap_neutral = pd.DataFrame()

    nonoverlap_summary = pd.concat(
        [nonoverlap_directional, nonoverlap_neutral], ignore_index=True
    )
    nonoverlap_summary.to_csv(OUT / "nonoverlap_summary.csv", index=False)
    cost_sensitivity.to_csv(OUT / "cost_sensitivity.csv", index=False)

    # Label-level robustness is kept separate; different labels may overlap each other.
    label_keys = [
        "symbol", "timeframe", "period", "feature", "label", "direction",
        "metric", "horizon_bars",
    ]
    label_ordered = df.sort_values(
        label_keys + ["entry_timestamp_dt", "signal_timestamp_dt", "exit_timestamp_dt"],
        kind="mergesort",
    ).reset_index(drop=True)
    label_positions: list[int] = []
    for _, positions in label_ordered.groupby(label_keys, sort=False, dropna=False).indices.items():
        last_exit = None
        for pos in positions:
            row = label_ordered.iloc[pos]
            if last_exit is None or row["entry_timestamp_dt"] > last_exit:
                label_positions.append(pos)
                last_exit = row["exit_timestamp_dt"]
    label_nonoverlap = label_ordered.iloc[label_positions].copy()
    label_nonoverlap["win_at_cost"] = np.where(
        label_nonoverlap["metric"] == "DIRECTIONAL_NET_RETURN",
        label_nonoverlap["event_value"] > 0,
        np.nan,
    )
    label_nonoverlap["value"] = label_nonoverlap["event_value"]
    label_nonoverlap["baseline"] = label_nonoverlap["matched_baseline"]
    label_summary = (
        label_nonoverlap.groupby(
            ["period", "feature", "label", "direction", "metric", "timeframe", "horizon_bars"],
            dropna=False,
        )
        .agg(
            events=("value", "size"),
            symbols=("symbol", "nunique"),
            mean_value=("value", "mean"),
            mean_baseline=("baseline", "mean"),
            mean_excess=("excess_vs_baseline", "mean"),
            win_rate=("win_at_cost", "mean"),
        )
        .reset_index()
    )
    label_summary.to_csv(OUT / "nonoverlap_by_label.csv", index=False)

    # Per-symbol sign robustness across the 44 names. This is a simple
    # one-sided sign test, not a return-distribution model. Adjust across all
    # tested label/timeframe/horizon groups with Benjamini-Hochberg.
    validation_directional = label_nonoverlap[
        (label_nonoverlap["period"] == "validation")
        & (label_nonoverlap["metric"] == "DIRECTIONAL_NET_RETURN")
    ].copy()
    per_symbol = (
        validation_directional.groupby(
            ["feature", "label", "direction", "timeframe", "horizon_bars", "symbol"],
            dropna=False,
        )
        .agg(
            events=("event_value", "size"),
            mean_net_return=("event_value", "mean"),
            mean_excess_vs_baseline=("excess_vs_baseline", "mean"),
            win_rate=("win_at_cost", "mean"),
        )
        .reset_index()
    )
    sign_robustness = (
        per_symbol.groupby(
            ["feature", "label", "direction", "timeframe", "horizon_bars"],
            dropna=False,
        )
        .agg(
            symbols=("symbol", "nunique"),
            events=("events", "sum"),
            equal_symbol_mean_net_return=("mean_net_return", "mean"),
            equal_symbol_mean_excess=("mean_excess_vs_baseline", "mean"),
            equal_symbol_win_rate=("win_rate", "mean"),
            positive_net_symbols=("mean_net_return", lambda x: int((x > 0).sum())),
            positive_excess_symbols=("mean_excess_vs_baseline", lambda x: int((x > 0).sum())),
        )
        .reset_index()
    )
    sign_robustness["p_sign_net_one_sided"] = sign_robustness.apply(
        lambda row: one_sided_sign_p(int(row["positive_net_symbols"]), int(row["symbols"])), axis=1
    )
    sign_robustness["p_sign_excess_one_sided"] = sign_robustness.apply(
        lambda row: one_sided_sign_p(int(row["positive_excess_symbols"]), int(row["symbols"])), axis=1
    )
    sign_robustness["q_sign_net_BH"] = benjamini_hochberg(sign_robustness["p_sign_net_one_sided"])
    sign_robustness["q_sign_excess_BH"] = benjamini_hochberg(sign_robustness["p_sign_excess_one_sided"])
    sign_robustness.to_csv(OUT / "per_symbol_sign_robustness.csv", index=False)

    report = {
        "status": "PASS",
        "source": str(SOURCE),
        "input_event_count": int(input_event_count),
        "rows_after_ambiguous_exclusion_and_deduplication": int(len(df)),
        "family_nonoverlap_event_count": int(len(nonoverlap)),
        "family_nonoverlap_fraction": float(len(nonoverlap) / len(df)),
        "label_level_nonoverlap_event_count": int(len(label_nonoverlap)),
        "ambiguous_conflicting_direction_rows_excluded": int(ambiguous_rows_excluded),
        "same_bar_duplicate_labels_collapsed": int(same_bar_duplicates_collapsed),
        "selection": "Greedy chronological intervals within symbol/timeframe/period/feature/metric/horizon; next entry must occur strictly after previous selected exit. Same-bar same-direction labels collapse; conflicting same-bar directions are excluded.",
        "equal_symbol_weighting": "Average event outcomes within each symbol, then average symbol means equally.",
        "base_round_trip_cost": BASE_ROUND_TRIP_COST,
        "round_trip_cost_sensitivity": list(ROUND_TRIP_COSTS),
        "validation_sign_test_groups": int(len(sign_robustness)),
        "minimum_BH_q_for_positive_net_sign": float(sign_robustness["q_sign_net_BH"].min()) if len(sign_robustness) else None,
        "minimum_BH_q_for_positive_excess_sign": float(sign_robustness["q_sign_excess_BH"].min()) if len(sign_robustness) else None,
        "holdout_boundary": "All source events are already limited to dates before 2026-11-20.",
        "interpretation": "Exploratory robustness check only. Different horizons are separate samples and can overlap across horizon tables. Label-level summary removes overlap within each label but different labels can overlap. Matched baseline is the unconditional same-symbol/timeframe/period/horizon average from the original event study. Sign tests treat symbols as independent for a simple robustness diagnostic; MOEX stocks may be cross-correlated, and BH adjustment does not correct market-wide dependence or all research-selection effects.",
    }
    (OUT / "nonoverlap_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
