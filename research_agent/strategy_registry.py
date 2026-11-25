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
    average = candidate.get("average_net_return")
    profit_factor = candidate.get("profit_factor")
    profit_factor_infinite = candidate.get("profit_factor_infinite") is True
    if not isinstance(average, (int, float)) or average <= 0:
        return "REJECT", ["Average net return is missing or not positive"]
    if not profit_factor_infinite and (
        not isinstance(profit_factor, (int, float)) or profit_factor <= 1
    ):
        return "REJECT", ["Profit factor is missing or not above one or infinite"]
    if not isinstance(stress, dict) or stress.get("survives_double_costs") is not True:
        return "REJECT", ["Candidate did not pass the doubled-cost screen"]
    stressed_average = stress.get("double_cost_average_net_return")
    if not isinstance(stressed_average, (int, float)) or stressed_average <= 0:
        return "REJECT", ["Doubled-cost average net return is missing or not positive"]
    return "PASS", ["Development screen and doubled-cost screen passed"]

def build_strategy_registry(report: dict[str, Any]) -> dict[str, Any]:
    results = report.get("results")
    if not isinstance(results, dict):
        raise ValueError("research report must contain a results object")
    supplied_universe = report.get("universe")
    if supplied_universe is None:
        expected_tickers = sorted(results)
    elif (not isinstance(supplied_universe, list)
          or any(not isinstance(ticker, str) or not ticker for ticker in supplied_universe)
          or len(supplied_universe) != len(set(supplied_universe))):
        raise ValueError("research report universe must be a unique list of ticker strings")
    else:
        expected_tickers = list(supplied_universe)
    analyzed_tickers = sorted(
        ticker for ticker in expected_tickers
        if isinstance(results.get(ticker), dict)
        and results[ticker].get("status") == "ANALYZED"
    )
    unavailable_tickers = sorted(set(expected_tickers) - set(analyzed_tickers))
    unexpected_tickers = sorted(set(results) - set(expected_tickers))
    coverage_complete = (
        bool(expected_tickers)
        and not unavailable_tickers
        and not unexpected_tickers
        and len(results) == len(expected_tickers)
    )
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
                stress_item = stressed.get(strategy) or {}
                stress_by_direction = stress_item.get("by_direction") or {}
                stress = stress_by_direction.get(direction) if isinstance(stress_by_direction, dict) else None
                status, reasons = _candidate_status(candidate, stress)
                if not analyzed:
                    reasons = [str(item.get("status", "Ticker not analyzed")) if isinstance(item, dict) else "Ticker not analyzed"]
                entry = {
                    "ticker": ticker, "direction": direction, "strategy": strategy,
                    "status": status, "reasons": reasons,
                    "closed_trades": (candidate or {}).get("closed_trades"),
                    "average_net_return": (candidate or {}).get("average_net_return"),
                    "profit_factor": (candidate or {}).get("profit_factor"),
                    "profit_factor_infinite": (candidate or {}).get("profit_factor_infinite", False),
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
        "source_report_date_till": report.get("date_till"),
        "holdout_start": (report.get("development_holdout_policy") or {}).get("holdout_start"),
        "holdout_used_for_selection": False,
        "selection_policy": {
            "minimum_closed_trades": 30, "all_walk_forward_folds_must_meet_minimum": True,
            "minimum_trades_per_fold": 5, "positive_average_net_return": True,
            "profit_factor_above_one": True, "doubled_cost_screen_must_pass": True,
            "directions_evaluated_independently": True,
        },
        "summary": summary, "strategies": entries,
        "coverage": {
            "expected_symbols": len(expected_tickers),
            "analyzed_symbols": len(analyzed_tickers),
            "unavailable_symbols": len(unavailable_tickers),
            "unavailable_tickers": unavailable_tickers,
            "unexpected_result_tickers": unexpected_tickers,
            "coverage_complete": coverage_complete,
        },
        "scanner_contract": {
            "consume_only_status": "PASS" if coverage_complete else "BLOCKED_INCOMPLETE_COVERAGE",
            "require_eligible_for_shadow_scanner": True,
            "live_trading_authorized": False,
            "note": "PASS is a preliminary development screen only; no production or broker execution approval.",
        },
    }
