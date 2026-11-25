"""Trust boundary between AI-proposed MOEX signals and deterministic verification.

AI agents may suggest candidates. This module never calculates indicators or
trusts AI claims: it reproduces each candidate against a deterministic scan and
labels it using the independently generated strategy registry and H1 result.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

REPORT_STATUS = "AGENT_SIGNAL_PROPOSALS"
SCAN_STATUS = "READ_ONLY_LATEST_SIGNAL_SCAN"
REGISTRY_STAGE = "DEVELOPMENT_ONLY_NOT_PRODUCTION_APPROVAL"
DIRECTIONS = {"LONG", "SHORT"}
ALLOWED_STRATEGIES = {
    "Donchian20", "EMA20x50", "RSI14Trend50", "MACD12x26", "Keltner20x2ATR"
}
ALLOWED_TIMEFRAMES = {"D1", "W1", "H1", "H4", "M15"}
MOSCOW = ZoneInfo("Europe/Moscow")


class AgentContractError(ValueError):
    """An AI proposal report violates the strict input contract."""


def _aware_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise AgentContractError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AgentContractError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AgentContractError(f"{field} must include a timezone")
    return parsed


def validate_agent_proposals(report: dict[str, Any], universe: list[str]) -> None:
    """Validate untrusted agent output without promoting any proposal."""
    if not isinstance(report, dict) or report.get("status") != REPORT_STATUS:
        raise AgentContractError("Unexpected agent proposal report status")
    _aware_utc(report.get("generated_at_utc"), "generated_at_utc")
    run_id = report.get("agent_run_id")
    if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 128:
        raise AgentContractError("agent_run_id must be a non-empty string")
    proposals = report.get("proposals")
    if not isinstance(proposals, list) or len(proposals) > 1000:
        raise AgentContractError("proposals must be a list of at most 1000 items")
    seen = set()
    for index, proposal in enumerate(proposals):
        if not isinstance(proposal, dict):
            raise AgentContractError(f"Proposal {index} must be an object")
        required = ("symbol", "direction", "strategy", "d1_bar_end_utc", "timeframes")
        missing = [key for key in required if key not in proposal]
        if missing:
            raise AgentContractError(f"Proposal {index} missing: {', '.join(missing)}")
        symbol = proposal["symbol"]
        if not isinstance(symbol, str) or symbol not in universe:
            raise AgentContractError(f"Proposal {index} uses a symbol outside the scan universe")
        if proposal["direction"] not in DIRECTIONS:
            raise AgentContractError(f"Proposal {index} has invalid direction")
        if proposal["strategy"] not in ALLOWED_STRATEGIES:
            raise AgentContractError(f"Proposal {index} uses an unsupported strategy")
        _aware_utc(proposal["d1_bar_end_utc"], f"proposal[{index}].d1_bar_end_utc")
        frames = proposal["timeframes"]
        if (not isinstance(frames, list) or
                any(not isinstance(frame, str) or frame not in ALLOWED_TIMEFRAMES for frame in frames) or
                not {"D1", "H1"}.issubset(frames) or
                len(set(frames)) != len(frames)):
            raise AgentContractError(f"Proposal {index} has invalid timeframes")
        key = (symbol, proposal["direction"], proposal["strategy"], proposal["d1_bar_end_utc"])
        if key in seen:
            raise AgentContractError(f"Duplicate proposal identity at index {index}")
        seen.add(key)
        explanation = proposal.get("rationale", "")
        if not isinstance(explanation, str) or len(explanation) > 2000:
            raise AgentContractError(f"Proposal {index} rationale must be a string up to 2000 chars")


def verify_agent_proposals(
    agent_report: dict[str, Any],
    deterministic_scan: dict[str, Any],
    strategy_registry: dict[str, Any],
) -> dict[str, Any]:
    """Reproduce agent candidates against deterministic signals and registry.

    Only candidates that exactly match symbol, direction, strategy and closed D1
    bar-end timestamp can proceed. H1 confirmation and research approval are
    independently checked. No agent-supplied price, indicator or performance
    metric is used.
    """
    if deterministic_scan.get("status") != SCAN_STATUS:
        raise AgentContractError("Deterministic scan is missing or has an unexpected status")
    if not isinstance(deterministic_scan.get("signals"), list):
        raise AgentContractError("Deterministic scan signals must be a list")
    scanner_contract = strategy_registry.get("scanner_contract") or {}
    if (strategy_registry.get("stage") != REGISTRY_STAGE or
            strategy_registry.get("holdout_used_for_selection") is not False or
            scanner_contract.get("live_trading_authorized") is not False):
        raise AgentContractError("Strategy registry is not a valid development-only registry")
    if scanner_contract.get("consume_only_status") != "PASS":
        raise AgentContractError("Strategy registry is blocked from scanner consumption")
    try:
        scan_cutoff = _aware_utc(deterministic_scan.get("as_of_utc"), "deterministic_scan.as_of_utc")
        registry_source_date = datetime.fromisoformat(
            strategy_registry.get("source_report_date_till")
        ).date()
    except (TypeError, ValueError) as exc:
        raise AgentContractError("Strategy registry or scan is missing a valid source date") from exc
    snapshot_date = scan_cutoff.astimezone(MOSCOW).date()
    registry_age_days = (snapshot_date - registry_source_date).days
    if registry_age_days < 0 or registry_age_days > 14:
        raise AgentContractError("Strategy registry source data is future-dated or older than 14 days")

    universe = deterministic_scan.get("universe") or []
    if not isinstance(universe, list) or any(not isinstance(item, str) for item in universe):
        raise AgentContractError("Deterministic scan universe must be a list of ticker strings")
    coverage = strategy_registry.get("coverage")
    if (not isinstance(coverage, dict)
            or coverage.get("coverage_complete") is not True
            or coverage.get("expected_symbols") != len(universe)
            or coverage.get("analyzed_symbols") != len(universe)
            or coverage.get("unavailable_symbols") != 0
            or coverage.get("unexpected_result_tickers")):
        raise AgentContractError(
            "Strategy registry has missing or incomplete full-universe research coverage"
        )
    validate_agent_proposals(agent_report, universe)
    reproduced = {
        (row.get("symbol"), row.get("direction"), row.get("strategy"), row.get("d1_bar_end_utc")): row
        for row in deterministic_scan["signals"]
    }
    registry = {
        (row.get("ticker"), row.get("direction"), row.get("strategy")): row
        for row in strategy_registry.get("strategies", [])
        if isinstance(row, dict)
    }

    results = []
    counts = {
        "CONFIRMED": 0,
        "VERIFIED_SIGNAL_H1_NOT_CONFIRMED": 0,
        "EXPERIMENTAL_STRATEGY_UNAPPROVED": 0,
        "REJECTED_NOT_REPRODUCED": 0,
    }
    for proposal in agent_report["proposals"]:
        key = (proposal["symbol"], proposal["direction"], proposal["strategy"], proposal["d1_bar_end_utc"])
        actual = reproduced.get(key)
        if actual is None:
            status = "REJECTED_NOT_REPRODUCED"
            reason = "No exact matching signal exists in the deterministic scan."
        else:
            eligibility = registry.get(key[:3], {})
            research_pass = eligibility.get("status") == "PASS" and eligibility.get("eligible_for_shadow_scanner") is True
            h1_status = actual.get("h1_confirmation")
            if not research_pass:
                status = "EXPERIMENTAL_STRATEGY_UNAPPROVED"
                reason = "Signal reproduced, but its strategy has not passed the independent research gate."
            elif h1_status != "CONFIRMED":
                status = "VERIFIED_SIGNAL_H1_NOT_CONFIRMED"
                reason = "Signal reproduced and strategy passed the research gate, but mandatory H1 confirmation is absent."
            else:
                status = "CONFIRMED"
                reason = "Exact deterministic signal reproduced; strategy passed the research gate and H1 is confirmed."
        counts[status] += 1
        results.append({
            "symbol": proposal["symbol"],
            "direction": proposal["direction"],
            "strategy": proposal["strategy"],
            "d1_bar_end_utc": proposal["d1_bar_end_utc"],
            "status": status,
            "reason": reason,
            "verified_signal": actual if actual is not None else None,
        })

    confirmed = [item for item in results if item["status"] == "CONFIRMED"]
    return {
        "status": "AGENT_SIGNAL_VERIFICATION_COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "agent_run_id": agent_report["agent_run_id"],
        "deterministic_scan_as_of_utc": deterministic_scan.get("as_of_utc"),
        "strategy_registry_version": strategy_registry.get("registry_version"),
        "proposal_count": len(results),
        "counts": counts,
        "confirmed_signals_count": len(confirmed),
        "confirmed_signals": confirmed,
        "results": results,
        "policy": {
            "ai_is_proposer_only": True,
            "deterministic_scan_is_signal_authority": True,
            "research_registry_is_strategy_authority": True,
            "mandatory_h1_confirmation": True,
            "live_trading_authorized": False,
            "agent_supplied_prices_indicators_and_performance_ignored": True,
        },
    }
