"""Run the v2 discovery loop over the frozen pre-holdout MOEX D1 universe.

This is an offline research command. It consumes a previously validated
multi-timeframe artifact, uses only native D1 rows before the sealed holdout,
and writes a research report. It never accesses broker or order APIs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .features import extract_ohlcv_features
from .moex_dataset import load_pre_holdout_d1
from .multiple_testing import holm_bonferroni
from .pipeline import run_research_pipeline


PREDECLARED_EXIT_RULES = {
    "LONG": {"conditions": [
        {"feature": "candle_body_pct", "operator": "<=", "threshold": 0.0}
    ]},
    "SHORT": {"conditions": [
        {"feature": "candle_body_pct", "operator": ">=", "threshold": 0.0}
    ]},
}


def run_moex_d1_research(
    dataset: dict[str, Any],
    *,
    formation_fraction: float = 0.70,
    max_features: int = 12,
    max_hypotheses_per_symbol: int = 20,
    min_trades_for_inference: int = 20,
    block_length: int = 5,
    resamples: int = 19_999,
    alpha: float = 0.05,
    commission_rate: float = 0.0008,
    slippage_rate: float = 0.0005,
    seed: int = 1729,
) -> dict[str, Any]:
    if isinstance(formation_fraction, bool) or not isinstance(formation_fraction, (int, float)) or not 0.5 <= formation_fraction <= 0.85:
        raise ValueError("formation_fraction must be between 0.5 and 0.85")
    if isinstance(max_hypotheses_per_symbol, bool) or not isinstance(max_hypotheses_per_symbol, int) or max_hypotheses_per_symbol < 1:
        raise ValueError("max_hypotheses_per_symbol must be a positive integer")
    if not isinstance(dataset, dict) or not isinstance(dataset.get("symbols"), dict) or not dataset["symbols"]:
        raise ValueError("dataset must contain loaded pre-holdout symbols")

    per_symbol: dict[str, Any] = {}
    global_p_values: dict[str, float] = {}
    global_row_refs: dict[str, tuple[str, dict[str, Any]]] = {}

    for symbol in sorted(dataset["symbols"]):
        bars = dataset["symbols"][symbol]
        formation_end = int(len(bars) * formation_fraction)
        if formation_end < 40 or len(bars) - formation_end < 20:
            per_symbol[symbol] = {
                "status": "INSUFFICIENT_HISTORY",
                "bar_count": len(bars),
            }
            continue

        features = extract_ohlcv_features(bars)
        result = run_research_pipeline(
            bars,
            features,
            PREDECLARED_EXIT_RULES,
            formation_end=formation_end,
            max_features=max_features,
            max_hypotheses=max_hypotheses_per_symbol,
            min_formation_observations=20,
            min_trades_for_inference=min_trades_for_inference,
            block_length=block_length,
            resamples=resamples,
            alpha=alpha,
            commission_rate=commission_rate,
            slippage_rate=slippage_rate,
            seed=seed,
            family_id=f"moex-d1-local-{symbol}-{dataset['holdout_start']}",
        )
        per_symbol[symbol] = {
            "status": result["status"],
            "bar_count": len(bars),
            "first_date": bars[0]["timestamp"][:10],
            "last_date": bars[-1]["timestamp"][:10],
            "formation_end_index": formation_end,
            "formation_bars": formation_end,
            "validation_bars": len(bars) - formation_end,
            "pipeline": result,
        }
        for row in result.get("results", []):
            key = f"{symbol}:{row['hypothesis']['id']}"
            p_value = (
                row["inference"]["two_sided_p_value"]
                if row["inference"] is not None else 1.0
            )
            global_p_values[key] = p_value
            global_row_refs[key] = (symbol, row)

    if not global_p_values:
        raise ValueError("no generated hypotheses were available for global correction")

    global_correction = holm_bonferroni(
        global_p_values,
        alpha=alpha,
        family_id=f"moex-d1-44-symbol-global-family-{dataset['holdout_start']}",
    )
    adjusted = {item["hypothesis_id"]: item for item in global_correction["results"]}
    candidates = []
    tested = 0
    underpowered = 0
    for key, (symbol, row) in global_row_refs.items():
        correction = adjusted[key]
        row["global_multiple_testing"] = correction
        interval = row["inference"]["confidence_interval"] if row["inference"] else None
        row["candidate_for_walk_forward"] = bool(
            row["inference_status"] == "TESTED"
            and correction["reject_null"]
            and interval is not None
            and interval["lower"] > 0.0
        )
        if row["inference_status"] == "TESTED":
            tested += 1
        else:
            underpowered += 1
        row["status"] = (
            "CANDIDATE_FOR_WALK_FORWARD"
            if row["candidate_for_walk_forward"]
            else ("INSUFFICIENT_DATA" if row["inference_status"] != "TESTED" else "NOT_SELECTED")
        )
        if row["candidate_for_walk_forward"]:
            candidates.append({
                "symbol": symbol,
                "hypothesis_id": row["hypothesis"]["id"],
                "direction": row["hypothesis"]["direction"],
                "global_adjusted_p_value": correction["holm_adjusted_p_value"],
                "mean_net_return": row["inference"]["observed_mean"],
                "confidence_interval": interval,
                "closed_trades": row["closed_trade_count"],
            })

    return {
        "status": "COMPLETED",
        "data": {
            "source": "MOEX ISS native TQBR D1 history",
            "generated_at_utc": dataset["generated_at_utc"],
            "holdout_start": dataset["holdout_start"],
            "universe_size": dataset["universe_size"],
            "pre_holdout_bars": dataset["total_pre_holdout_bars"],
            "post_holdout_rows_excluded": dataset["post_holdout_rows_excluded"],
            "validation": dataset["validation"],
        },
        "research_design": {
            "formation_fraction": float(formation_fraction),
            "entry_hypotheses_generated_from_formation_only": True,
            "validation_window_ends_before_sealed_holdout": True,
            "final_holdout_used": False,
            "exit_rules": PREDECLARED_EXIT_RULES,
            "exit_rule_policy": "predeclared candle-body reversal; not optimized on validation",
            "execution": {
                "signal": "completed daily close",
                "fill": "next daily open",
                "commission_rate_per_side": commission_rate,
                "slippage_rate_per_side": slippage_rate,
                "position_policy": "one position at a time per symbol",
            },
            "inference": {
                "method": "circular moving-block bootstrap",
                "block_length_trades": block_length,
                "resamples": resamples,
                "min_closed_trades": min_trades_for_inference,
                "multiple_testing": "one global Holm family across all symbols and generated hypotheses",
                "underpowered_hypotheses": "retained in family with p=1 placeholder; not a measured p-value",
            },
            "strategy_approval": "NOT_APPROVED",
        },
        "global_family": global_correction,
        "summary": {
            "symbols_processed": sum(item.get("status") == "COMPLETED" for item in per_symbol.values()),
            "symbols_insufficient_history": sum(item.get("status") == "INSUFFICIENT_HISTORY" for item in per_symbol.values()),
            "hypotheses_in_global_family": len(global_p_values),
            "hypotheses_with_valid_bootstrap_tests": tested,
            "underpowered_hypotheses": underpowered,
            "candidates_for_walk_forward": len(candidates),
        },
        "candidates_for_walk_forward": candidates,
        "per_symbol": per_symbol,
        "safety": {
            "post_holdout_ohlcv_used": False,
            "lookahead_used_for_generation": False,
            "global_multiple_testing_applied": True,
            "capital_or_position_sizing_used": False,
            "broker_or_live_trading_accessed": False,
            "live_trading_enabled": False,
            "strategy_approval": "NOT_APPROVED",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MOEX EDGE v2 autonomous D1 research on pre-holdout data")
    parser.add_argument("--data", required=True, help="multi-timeframe candle JSON from the collector artifact")
    parser.add_argument("--validation", required=True, help="matching multi-timeframe validation JSON")
    parser.add_argument("--output", default="moex_edge_v2_d1_research.json")
    parser.add_argument("--holdout-start", default="2026-11-20")
    parser.add_argument("--formation-fraction", type=float, default=0.70)
    parser.add_argument("--max-hypotheses-per-symbol", type=int, default=20)
    parser.add_argument("--resamples", type=int, default=19_999)
    parser.add_argument("--commission-rate", type=float, default=0.0008)
    parser.add_argument("--slippage-rate", type=float, default=0.0005)
    args = parser.parse_args()

    dataset = load_pre_holdout_d1(
        args.data, args.validation, holdout_start=args.holdout_start
    )
    result = run_moex_d1_research(
        dataset,
        formation_fraction=args.formation_fraction,
        max_hypotheses_per_symbol=args.max_hypotheses_per_symbol,
        resamples=args.resamples,
        commission_rate=args.commission_rate,
        slippage_rate=args.slippage_rate,
    )
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": result["status"],
        "data": result["data"],
        "summary": result["summary"],
        "candidates_for_walk_forward": result["candidates_for_walk_forward"],
        "safety": result["safety"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
