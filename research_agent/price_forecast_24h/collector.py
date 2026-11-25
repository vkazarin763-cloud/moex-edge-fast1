"""Prospective, read-only daily delta collector for the 24h price forecast study."""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from research_agent.multi_timeframe import DEFAULT_TICKERS, collect_multi_timeframe

DATA_DIR = Path("research_agent/price_forecast_24h/data")
STATE_FILE = DATA_DIR / "LATEST.json"


def _read_previous_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read previous collector state: {exc}") from exc


def _latest_h1_by_symbol(state: dict) -> dict[str, str]:
    return state.get("latest_h1", {}) if isinstance(state.get("latest_h1", {}), dict) else {}


def build_daily_delta(payload: dict, state: dict) -> tuple[dict, dict]:
    """Keep only bars newer than the last committed snapshot; never fill gaps."""
    previous_h1 = _latest_h1_by_symbol(state)
    previous_d1 = state.get("latest_d1", {})
    delta = {
        "schema_version": 1,
        "generated_at_utc": payload["generated_at_utc"],
        "timezone": payload["timezone"],
        "source_policy": "H1=Finam completed bars; D1=MOEX ISS TQBR history with official VALUE turnover",
        "symbols": {},
    }
    next_h1 = dict(previous_h1)
    next_d1 = dict(previous_d1)

    for ticker, frames in payload["results"].items():
        h1_block = frames.get("H1", {})
        d1_block = frames.get("D1", {})
        h1_candles = h1_block.get("candles", [])
        d1_candles = d1_block.get("candles", [])
        h1_after = previous_h1.get(ticker, "")
        d1_after = previous_d1.get(ticker, "")
        new_h1 = [row for row in h1_candles if row["timestamp"] > h1_after]
        new_d1 = [row for row in d1_candles if row["timestamp"][:10] > d1_after]
        if new_h1 or new_d1:
            delta["symbols"][ticker] = {
                "H1": new_h1,
                "D1": new_d1,
                "H1_source": h1_block.get("source"),
                "D1_source": d1_block.get("source"),
                "D1_value_missing": sum(row.get("value") is None for row in new_d1),
            }
        if new_h1:
            next_h1[ticker] = max(row["timestamp"] for row in new_h1)
        if new_d1:
            next_d1[ticker] = max(row["timestamp"][:10] for row in new_d1)

    state_out = {
        "schema_version": 1,
        "latest_h1": next_h1,
        "latest_d1": next_d1,
        "updated_at_utc": payload["generated_at_utc"],
    }
    return delta, state_out


def main() -> None:
    token = os.environ.get("FINAM_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("FINAM_API_TOKEN secret is required; its value is never printed")
    source_app_id = os.environ.get("FINAM_SOURCE_APP_ID", "").strip() or None
    tickers = [item.strip().upper() for item in os.environ.get("TICKERS", "").split(",") if item.strip()]
    if not tickers:
        tickers = DEFAULT_TICKERS

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = _read_previous_state()
    payload = collect_multi_timeframe(
        tickers, api_token=token, source_app_id=source_app_id, frames=("H1", "D1")
    )
    delta, state_out = build_daily_delta(payload, state)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    output = DATA_DIR / f"snapshot-{stamp}-{run_id}.json.gz"
    if output.exists():
        raise SystemExit(f"Snapshot already exists for this run; refusing to overwrite: {output}")
    with output.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            compressed.write((json.dumps(delta, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    STATE_FILE.write_text(json.dumps(state_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    missing_value = sum(
        item.get("D1_value_missing", 0) for item in delta["symbols"].values()
    )
    print(json.dumps({
        "status": "OK",
        "snapshot": str(output),
        "symbols_with_new_data": len(delta["symbols"]),
        "new_h1_bars": sum(len(item["H1"]) for item in delta["symbols"].values()),
        "new_d1_rows": sum(len(item["D1"]) for item in delta["symbols"].values()),
        "d1_rows_missing_official_value": missing_value,
        "note": "Missing VALUE rows are retained as missing and excluded from liquidity ranking; no close*volume substitution.",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
