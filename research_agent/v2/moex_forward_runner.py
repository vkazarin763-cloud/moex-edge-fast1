"""Evaluate formation-only hypotheses on a separate fresh MOEX forward window."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .bootstrap import moving_block_bootstrap_mean_test
from .cross_sectional import extract_cross_sectional_features
from .discovery import generate_hypotheses, generate_exit_hypotheses
from .execution import evaluate_hypothesis
from .features import extract_ohlcv_features
from .moex_forward_dataset import load_formation_and_forward_d1
from .multiple_testing import holm_bonferroni


def run_moex_forward_validation(
    dataset: dict[str, Any],
    *,
    formation_fraction: float = 0.70,
    max_features: int = 20,
    max_hypotheses_per_symbol: int = 20,
    max_exit_hypotheses: int = 2,
    min_trades_for_inference: int = 20,
    block_length: int = 5,
    resamples: int = 49_999,
    alpha: float = 0.05,
    commission_rate: float = 0.0008,
    slippage_rate: float = 0.0005,
    seed: int = 1729,
) -> dict[str, Any]:
    if not isinstance(dataset, dict) or not isinstance(dataset.get("formation_symbols"), dict):
        raise ValueError("dataset must contain formation_symbols")
    if not isinstance(dataset.get("forward_symbols"), dict):
        raise ValueError("dataset must contain forward_symbols")
    if not dataset.get("ready_for_forward_evaluation"):
        return {
            "status": "WAITING_FOR_FRESH_DATA",
            "data": {
                "generated_at_utc": dataset.get("generated_at_utc"),
                "sealed_through": dataset.get("sealed_through"),
                "universe_size": dataset.get("universe_size"),
                "forward_date_count": dataset.get("forward_date_count"),
                "minimum_forward_bars_per_symbol": dataset.get("minimum_forward_bars_per_symbol"),
                "minimum_forward_bars_required": dataset.get("minimum_forward_bars_required"),
            },
            "summary": {"candidates_evaluated": 0, "candidates_for_walk_forward": 0},
            "safety": {
                "historical_validation_tail_used": False,
                "sealed_holdout_used": False,
                "forward_data_used_for_generation": False,
                "strategy_approval": "NOT_APPROVED",
            },
        }
    if not 0.5 <= formation_fraction <= 0.85:
        raise ValueError("formation_fraction must be between 0.5 and 0.85")

    combined = {
        symbol: list(dataset["formation_symbols"][symbol]) + list(dataset["forward_symbols"][symbol])
        for symbol in sorted(dataset["formation_symbols"])
    }
    base_features = {
        symbol: extract_ohlcv_features(bars)
        for symbol, bars in combined.items()
    }
    cross_features = extract_cross_sectional_features(
        combined, horizons=(5, 20), min_coverage_fraction=0.5
    )

    per_symbol: dict[str, Any] = {}
    global_p_values: dict[str, float] = {}
    row_refs: dict[str, tuple[str, dict[str, Any]]] = {}

    for symbol in sorted(combined):
        history = dataset["formation_symbols"][symbol]
        forward = dataset["forward_symbols"][symbol]
        formation_end = int(len(history) * formation_fraction)
        if formation_end < 40 or len(forward) < dataset["minimum_forward_bars_required"]:
            per_symbol[symbol] = {
                "status": "INSUFFICIENT_HISTORY_OR_FORWARD_DATA",
                "historical_bars": len(history),
                "forward_bars": len(forward),
            }
            continue

        full_features = dict(base_features[symbol])
        full_features.update(cross_features[symbol])
        formation_panel = {
            name: values[:formation_end]
            for name, values in full_features.items()
        }
        discovery = generate_hypotheses(
            formation_panel,
            formation_indices=list(range(formation_end)),
            max_features=max_features,
            max_hypotheses=max_hypotheses_per_symbol,
            min_observations=20,
        )
        hypotheses = discovery["hypotheses"]
        forward_start = len(history)
        forward_panel = {
            name: values[forward_start:]
            for name, values in full_features.items()
        }
        symbol_rows = []
        for entry in hypotheses:
            exits = generate_exit_hypotheses(
                formation_panel,
                formation_indices=list(range(formation_end)),
                entry_hypothesis=entry,
                max_exit_hypotheses=max_exit_hypotheses,
                min_observations=20,
            )["hypotheses"]
            for exit_rule in exits:
                candidate_id = f"{entry['id']}::{exit_rule['id']}"
                execution = evaluate_hypothesis(
                    forward, forward_panel, entry, exit_rule,
                    commission_rate=commission_rate,
                    slippage_rate=slippage_rate,
                )
                returns = [trade["net_return"] for trade in execution["trades"]]
                inference = None
                if len(returns) >= min_trades_for_inference and block_length <= len(returns) // 2:
                    inference = moving_block_bootstrap_mean_test(
                        returns, block_length=block_length,
                        resamples=resamples, alpha=alpha, seed=seed,
                    )
                    p_value = inference["two_sided_p_value"]
                    inference_status = "TESTED"
                else:
                    p_value = 1.0
                    inference_status = "INSUFFICIENT_DATA"
                row = {
                    "candidate_id": candidate_id,
                    "entry_hypothesis": entry,
                    "exit_hypothesis": exit_rule,
                    "direction": entry["direction"],
                    "execution": execution,
                    "closed_trade_count": len(returns),
                    "inference": inference,
                    "inference_status": inference_status,
                    "approval_status": "NOT_APPROVED",
                }
                global_p_values[f"{symbol}:{candidate_id}"] = p_value
                row_refs[f"{symbol}:{candidate_id}"] = (symbol, row)
                symbol_rows.append(row)

        per_symbol[symbol] = {
            "status": "EVALUATED",
            "historical_bars_available": len(history),
            "formation_bars_used": formation_end,
            "historical_tail_bars_not_used": len(history) - formation_end,
            "forward_bars_used": len(forward),
            "first_forward_date": forward[0]["timestamp"][:10],
            "last_forward_date": forward[-1]["timestamp"][:10],
            "eligible_features": discovery["eligible_features"],
            "entry_hypotheses_generated": len(hypotheses),
            "entry_exit_pairs_evaluated": len(symbol_rows),
            "results": symbol_rows,
        }

    if not global_p_values:
        return {
            "status": "NO_HYPOTHESES_GENERATED",
            "data": {"sealed_through": dataset["sealed_through"]},
            "summary": {"candidates_evaluated": 0, "candidates_for_walk_forward": 0},
            "per_symbol": per_symbol,
            "safety": {"strategy_approval": "NOT_APPROVED"},
        }

    correction = holm_bonferroni(
        global_p_values,
        alpha=alpha,
        family_id=f"moex-d1-fresh-forward-after-{dataset['sealed_through']}",
    )
    corrected = {item["hypothesis_id"]: item for item in correction["results"]}
    candidates = []
    tested = 0
    underpowered = 0
    for key, (symbol, row) in row_refs.items():
        adjusted = corrected[key]
        row["global_multiple_testing"] = adjusted
        interval = row["inference"]["confidence_interval"] if row["inference"] else None
        row["candidate_for_walk_forward"] = bool(
            row["inference_status"] == "TESTED"
            and adjusted["reject_null"]
            and interval is not None
            and interval["lower"] > 0.0
        )
        row["status"] = (
            "CANDIDATE_FOR_WALK_FORWARD" if row["candidate_for_walk_forward"]
            else ("INSUFFICIENT_DATA" if row["inference_status"] != "TESTED" else "NOT_SELECTED")
        )
        if row["inference_status"] == "TESTED":
            tested += 1
        else:
            underpowered += 1
        if row["candidate_for_walk_forward"]:
            candidates.append({
                "symbol": symbol,
                "direction": row["direction"],
                "entry_rule": row["entry_hypothesis"]["conditions"],
                "exit_rule": row["exit_hypothesis"]["conditions"],
                "global_adjusted_p_value": adjusted["holm_adjusted_p_value"],
                "mean_net_return": row["inference"]["observed_mean"],
                "confidence_interval": interval,
                "closed_trades": row["closed_trade_count"],
            })

    return {
        "status": "COMPLETED",
        "data": {
            "source": "MOEX ISS native TQBR D1 history",
            "generated_at_utc": dataset["generated_at_utc"],
            "sealed_through": dataset["sealed_through"],
            "universe_size": dataset["universe_size"],
            "forward_date_count": dataset["forward_date_count"],
            "minimum_forward_bars_per_symbol": dataset["minimum_forward_bars_per_symbol"],
            "sealed_date_rows_skipped_without_ohlcv_parsing": dataset["sealed_date_rows_skipped_without_ohlcv_parsing"],
        },
        "research_design": {
            "historical_formation_fraction": formation_fraction,
            "historical_formation_only_used_for_generation": True,
            "historical_validation_tail_used": False,
            "fresh_forward_window_used_for_evaluation_only": True,
            "sealed_2026_11_20_holdout_used": False,
            "entry_exit_pairs_in_one_global_holm_family": True,
            "execution": {
                "signal": "completed daily close",
                "fill": "next daily open",
                "commission_rate_per_side": commission_rate,
                "slippage_rate_per_side": slippage_rate,
            },
            "inference": {
                "method": "circular moving-block bootstrap",
                "block_length_trades": block_length,
                "resamples": resamples,
                "minimum_closed_trades": min_trades_for_inference,
                "underpowered_candidates_retained_with_p1_placeholder": True,
            },
            "strategy_approval": "NOT_APPROVED",
        },
        "global_family": correction,
        "summary": {
            "candidates_evaluated": len(global_p_values),
            "hypotheses_with_valid_bootstrap_tests": tested,
            "underpowered_hypotheses": underpowered,
            "candidates_for_walk_forward": len(candidates),
        },
        "candidates_for_walk_forward": candidates,
        "per_symbol": per_symbol,
        "safety": {
            "sealed_holdout_used": False,
            "historical_validation_tail_used": False,
            "forward_data_used_for_generation": False,
            "forward_data_used_for_evaluation_only": True,
            "lookahead_used": False,
            "global_multiple_testing_applied": True,
            "capital_or_position_sizing_used": False,
            "broker_or_live_trading_accessed": False,
            "strategy_approval": "NOT_APPROVED",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate MOEX EDGE hypotheses on fresh forward D1 data")
    parser.add_argument("--data", required=True)
    parser.add_argument("--validation", required=True)
    parser.add_argument("--output", default="moex_edge_v2_forward_validation.json")
    parser.add_argument("--sealed-through", default="2026-11-20")
    parser.add_argument("--minimum-forward-bars", type=int, default=20)
    parser.add_argument("--resamples", type=int, default=49_999)
    args = parser.parse_args()

    dataset = load_formation_and_forward_d1(
        args.data, args.validation,
        sealed_through=args.sealed_through,
        minimum_forward_bars=args.minimum_forward_bars,
    )
    result = run_moex_forward_validation(dataset, resamples=args.resamples)
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": result["status"],
        "data": result.get("data"),
        "summary": result.get("summary"),
        "safety": result.get("safety"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
