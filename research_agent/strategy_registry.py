"""Machine-readable strategy selection output for the MOEX EDGE shadow scanner.
PASS is a development-only screen result, not production approval.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

REGISTRY_VERSION = "development-registry-v1"
DIRECTIONS = ("LONG", "SHORT")
STRATEGIES = ("Donchian20", "EMA20x50", "RSI14Trend50", "MACD12x26", "Keltner20x2ATR")

def _candidate_status(candidate: dict[str, Any] | None, stress: dict[str, Any] | None) -> tuple[str, list[str]]:
    if not isinstance(candidate, dict):
        return "INSUFFICIENT_DATA", ["No walk-forward candidate result"]
    trades = int(candidate.get("closed_trades") or 0)
    folds = int(candidate.get("folds") or 0)
    adequate = int(candidate.get("adequately_sampled_folds") or 0)
    reasons = []
    if trades < 30:
        reasons.append(f"Only {trades} closed trades; minimum is 30")
    if folds < 1 or adequate < folds:
        reasons.append(f"Only {adequate} of {folds} folds meet minimum trade count")
    if reasons:
        return "INSUFFICIENT_DATA", reasons
    if candidate.get("status") != "DEVELOPMENT_SCREEN_PASS_UNADJUSTED":
        return "REJECT", ["Development walk-forward screen did not pass"]
    if not isinstance(stress, dict) or stress.get("survives_double_costs") is not True:
        return "REJECT", ["Candidate did not pass the doubled-cost screen"]
    return "PASS", ["Development screen and doubled-cost screen passed"]

def build_strategy_registry(report: dict[str, Any]) -> dict[str, Any]:
    results = report.get("results")
    if not isinstance(results, dict):
        raise ValueError("research report must contain a results object")
    entries = []
    summary = {"PASS": 0, "REJECT": 0, "INSUFFICIENT_DATA": 0}
    for ticker in sorted(results):
        item = results[ticker]
        analyzed = isinstance(item, dict) and item.get("status") == "ANALYZED"
        walk = (item.get("walk_forward") or {}) if analyzed else {}
        stressed = ((item.get("adversarial_cost_check") or {}).get("candidates") or {}) if analyzed else {}
        for direction in DIRECTIONS:
            candidates = (walk.get("by_direction") or {}).get(direction) or {}
            for strategy in STRATEGIES:
                candidate = candidates.get(strategy) if analyzed else None
                stress = (stressed.get(strategy) or {}).get("by_direction", {}).get(direction)
                status, reasons = _candidate_status(candidate, stress)
                if not analyzed:
                    reasons = [str(item.get("status", "Ticker not analyzed")) if isinstance(item, dict) else "Ticker not analyzed"]
                entry = {
                    "ticker": ticker, "direction": direction, "strategy": strategy,
                    "status": status, "reasons": reasons,
                    "closed_trades": (candidate or {}).get("closed_trades"),
                    "average_net_return": (candidate or {}).get("average_net_return"),
                    "profit_factor": (candidate or {}).get("profit_factor"),
                    "positive_folds": (candidate or {}).get("positive_folds"),
                    "adequately_sampled_folds": (candidate or {}).get("adequately_sampled_folds"),
                    "folds": (candidate or {}).get("folds"),
                    "double_cost_average_net_return": (stress or {}).get("double_cost_average_net_return"),
                    "eligible_for_shadow_scanner": status == "PASS",
                }
                entries.append(entry)
                summary[status] += 1
    return {
        "registry_version": REGISTRY_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "DEVELOPMENT_ONLY_NOT_PRODUCTION_APPROVAL",
        "source_report_generated_at_utc": report.get("generated_at_utc"),
        "holdout_start": (report.get("development_holdout_policy") or {}).get("holdout_start"),
        "holdout_used_for_selection": False,
        "selection_policy": {
            "minimum_closed_trades": 30, "all_walk_forward_folds_must_meet_minimum": True,
            "minimum_trades_per_fold": 5, "positive_average_net_return": True,
            "profit_factor_above_one": True, "doubled_cost_screen_must_pass": True,
            "directions_evaluated_independently": True,
        },
        "summary": summary, "strategies": entries,
        "scanner_contract": {
            "consume_only_status": "PASS", "require_eligible_for_shadow_scanner": True,
            "live_trading_authorized": False,
            "note": "PASS is a preliminary development screen only; no production or broker execution approval.",
        },
    }
