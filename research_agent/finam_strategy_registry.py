"""Fail-closed development registry adapter for the one-year Finam D1 report.

The Finam exploratory report does not yet contain four independent walk-forward
folds per ticker/strategy/direction. Therefore this adapter can never approve a
strategy: it records data coverage and leaves every candidate INSUFFICIENT_DATA.
"""
from __future__ import annotations

from typing import Any

from .strategy_registry import build_strategy_registry

EXPECTED_HOLDOUT_START = "2026-11-20"
EXPECTED_SOURCE = "Finam Trade API TIME_FRAME_D, native D1 bars"


def build_finam_strategy_registry(report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise ValueError("Finam report must be an object")
    if report.get("source") != EXPECTED_SOURCE:
        raise ValueError("Registry accepts only native Finam D1 reports")
    if report.get("holdout_start") != EXPECTED_HOLDOUT_START:
        raise ValueError("Finam report holdout boundary does not match the frozen policy")
    if report.get("holdout_used_for_selection") is True:
        raise ValueError("Frozen holdout must not be used for strategy selection")

    universe = report.get("universe")
    audit = report.get("data_audit")
    if (not isinstance(universe, list) or not universe
            or any(not isinstance(t, str) or not t for t in universe)
            or len(universe) != len(set(universe))):
        raise ValueError("Finam report must contain a non-empty unique universe")
    if not isinstance(audit, dict) or set(audit) != set(universe):
        raise ValueError("Finam data audit must cover the exact declared universe")

    results = {}
    for ticker in universe:
        item = audit[ticker]
        usable = (
            isinstance(item, dict)
            and item.get("status") == "OK"
            and isinstance(item.get("retained_completed_bars"), int)
            and item["retained_completed_bars"] >= 60
        )
        results[ticker] = {
            "status": "ANALYZED" if usable else "DATA_OR_ANALYSIS_ERROR",
            "data_source": "Finam Trade API TIME_FRAME_D",
        }

    registry_input = {
        "results": results,
        "universe": list(universe),
        "generated_at_utc": report.get("generated_at_utc"),
        "date_till": "2026-11-19",
        "development_holdout_policy": {"holdout_start": EXPECTED_HOLDOUT_START},
    }
    registry = build_strategy_registry(registry_input)
    registry["registry_version"] = "finam-one-year-no-walkforward-v1"
    registry["source_provider"] = "Finam Trade API"
    registry["source_timeframe"] = "D1"
    registry["source_history_calendar_days"] = 365
    registry["source_data_cutoff"] = "2026-11-19"
    registry["strategy_evidence_status"] = "NOT_ELIGIBLE_FOR_APPROVAL"
    registry["strategy_evidence_note"] = (
        "The one-year Finam exploratory report does not provide four independent "
        "walk-forward folds per ticker/strategy/direction. No strategy is approved; "
        "all registry entries remain INSUFFICIENT_DATA until a separate Finam-only "
        "walk-forward evaluation is implemented and passes the frozen gates."
    )
    for entry in registry["strategies"]:
        entry["status"] = "INSUFFICIENT_DATA"
        entry["eligible_for_shadow_scanner"] = False
        entry["reasons"] = [
            "Four independent Finam-only walk-forward folds have not been evaluated"
        ]
    registry["summary"] = {
        "PASS": 0,
        "REJECT": 0,
        "INSUFFICIENT_DATA": len(registry["strategies"]),
    }
    registry["scanner_contract"]["note"] = (
        "Full Finam data coverage is required, but no strategy is currently eligible. "
        "This registry cannot authorize signals or live trading."
    )
    return registry

def main() -> int:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Build a fail-closed Finam-only strategy registry")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = json.loads(Path(args.input).read_text(encoding="utf-8"))
    registry = build_finam_strategy_registry(report)
    Path(args.output).write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "registry_version": registry["registry_version"],
        "coverage": registry["coverage"],
        "summary": registry["summary"],
        "scanner_contract": registry["scanner_contract"],
        "strategy_evidence_status": registry["strategy_evidence_status"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
