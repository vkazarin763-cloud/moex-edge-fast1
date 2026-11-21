"""Append-only, read-only ledger for immutable MTF signal events.

This module does not fetch market data or access broker/execution interfaces.
It records first observation of each frozen-cohort signal identity. Later
outcome tracking is deliberately a separate component.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

REQUIRED_REPORT_FIELDS = (
    "status", "generated_at_utc", "as_of_utc", "strategy_cohort_version", "signals"
)
SIGNAL_FIELDS = (
    "symbol", "direction", "strategy", "d1_signal_timestamp", "d1_bar_end_utc",
    "d1_close", "parameters", "h1_confirmation", "h1",
)


class LedgerError(ValueError):
    """Invalid report or conflicting immutable signal record."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _signals_equivalent(left: Any, right: Any) -> bool:
    """Compare payloads while ignoring sub-tick floating-point noise.

    First-observed values remain untouched. Repeat-event validation allows
    only 1e-6 absolute numeric drift (well below MOEX price ticks); structural
    or material changes continue to fail closed.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-6)
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _signals_equivalent(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _signals_equivalent(a, b) for a, b in zip(left, right)
        )
    return type(left) is type(right) and left == right


def _event_id(cohort: str, signal: dict) -> str:
    identity = {
        "cohort": cohort,
        "symbol": signal["symbol"],
        "strategy": signal["strategy"],
        "direction": signal["direction"],
        "d1_bar_end_utc": signal["d1_bar_end_utc"],
    }
    return hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()


def _validate_report(report: dict) -> None:
    missing = [key for key in REQUIRED_REPORT_FIELDS if key not in report]
    if missing:
        raise LedgerError(f"Missing report fields: {', '.join(missing)}")
    if report["status"] != "READ_ONLY_LATEST_SIGNAL_SCAN":
        raise LedgerError("Unexpected report status")
    if not isinstance(report["signals"], list):
        raise LedgerError("signals must be a list")
    if not isinstance(report["strategy_cohort_version"], str) or not report["strategy_cohort_version"]:
        raise LedgerError("strategy_cohort_version must be non-empty")


def append_signal_report(report: dict, ledger_path: str | Path) -> dict:
    """Append unseen signal events; identical repeats are idempotently skipped."""
    _validate_report(report)
    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, dict] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    event_id = record["event_id"]
                    payload = record["signal"]
                    if not isinstance(payload, dict):
                        raise TypeError("signal must be an object")
                except (json.JSONDecodeError, KeyError, TypeError) as exc:
                    raise LedgerError(f"Invalid ledger row {line_number}") from exc
                if event_id in existing and not _signals_equivalent(existing[event_id], payload):
                    raise LedgerError(f"Conflicting duplicate already stored: {event_id}")
                existing[event_id] = payload

    added = 0
    duplicates = 0
    pending = []
    for index, signal in enumerate(report["signals"]):
        missing = [key for key in SIGNAL_FIELDS if key not in signal]
        if missing:
            raise LedgerError(f"Signal {index} missing fields: {', '.join(missing)}")
        if signal["direction"] not in ("LONG", "SHORT"):
            raise LedgerError(f"Signal {index} has invalid direction")
        event_id = _event_id(report["strategy_cohort_version"], signal)
        if event_id in existing:
            if not _signals_equivalent(existing[event_id], signal):
                raise LedgerError(f"Immutable signal changed after first observation: {event_id}")
            duplicates += 1
            continue
        record = {
            "schema_version": 1,
            "event_id": event_id,
            "cohort_version": report["strategy_cohort_version"],
            "first_observed_generated_at_utc": report["generated_at_utc"],
            "first_observed_as_of_utc": report["as_of_utc"],
            "signal": signal,
        }
        pending.append(_canonical(record))
        existing[event_id] = signal
        added += 1

    if pending:
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            for line in pending:
                stream.write(line + "\n")
            stream.flush()

    return {"added": added, "duplicates": duplicates, "total_events": len(existing)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Append immutable MTF signals to a JSONL ledger")
    parser.add_argument("--report", required=True, help="MTF scanner JSON report")
    parser.add_argument("--ledger", required=True, help="Append-only JSONL ledger path")
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    result = append_signal_report(report, args.ledger)
    print(
        f"Signal ledger: added={result['added']}, "
        f"duplicates={result['duplicates']}, total={result['total_events']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
