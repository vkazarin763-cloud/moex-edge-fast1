#!/usr/bin/env python3
"""Import an explicitly timestamped, read-only Finam MCP screener export.

Input JSON format:
{
  "retrieved_at": "2026-11-22T12:34:56Z",
  "responses": [<raw screen_securities response>, ...]
}

The timestamp must be the actual time the MCP responses were retrieved. This
script never calls Finam, reads credentials, or interacts with broker accounts.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_agent.finam_screener_adapter import (  # noqa: E402
    FinamScreenerDataError,
    normalize_screener_responses,
)


def load_export(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinamScreenerDataError(f"cannot read valid JSON export: {exc}") from exc
    if not isinstance(payload, dict):
        raise FinamScreenerDataError("input must be a JSON object")
    if not isinstance(payload.get("responses"), list) or len(payload["responses"]) != 5:
        raise FinamScreenerDataError("input must contain exactly five screener responses")
    if not isinstance(payload.get("retrieved_at"), str):
        raise FinamScreenerDataError("input must include the actual retrieved_at ISO timestamp")
    return payload


def write_snapshot(snapshot: dict, output: Path, *, force: bool = False) -> None:
    output = output.expanduser()
    if output.exists() and not force:
        raise FinamScreenerDataError(f"output already exists (use --force to replace): {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent,
            prefix=f".{output.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_name = handle.name
            handle.write(data)
            handle.flush()
        Path(temp_name).replace(output)
    finally:
        if temp_name and Path(temp_name).exists():
            Path(temp_name).unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSON export created by the authenticated MCP session")
    parser.add_argument("--output", required=True, type=Path, help="destination for the normalized snapshot JSON")
    parser.add_argument("--force", action="store_true", help="allow replacing an existing output file")
    args = parser.parse_args()

    try:
        exported = load_export(args.input)
        snapshot = normalize_screener_responses(
            exported["responses"], retrieved_at=exported["retrieved_at"]
        )
        write_snapshot(snapshot, args.output, force=args.force)
    except FinamScreenerDataError as exc:
        parser.error(str(exc))

    print(
        f"OK: {snapshot['received_count']}/{snapshot['expected_count']} symbols; "
        f"quote freshness={snapshot['quote_freshness']}; output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
