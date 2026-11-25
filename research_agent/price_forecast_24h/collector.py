"""Prospective, read-only collector: screen 44 candidates by official turnover, H1 only top 10."""
from __future__ import annotations

import gzip
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from research_agent.multi_timeframe import DEFAULT_TICKERS, collect_multi_timeframe

DATA_DIR = Path("research_agent/price_forecast_24h/data")
STATE_FILE = DATA_DIR / "LATEST.json"
LIQUIDITY_LOOKBACK_SESSIONS = 60
LIQUIDITY_MIN_VALID_SESSIONS = 40
LIQUIDITY_TOP_N = 10
OFFICIAL_D1_SOURCE = "MOEX ISS TQBR history"


def select_top_liquid(d1_payload: dict, *, top_n: int = LIQUIDITY_TOP_N) -> list[dict]:
    """Rank candidates by mean official VALUE over the latest 60 completed D1 sessions.

    A security is eligible only when its D1 source is MOEX ISS TQBR history and
    at least 40 of its latest 60 rows have finite, positive official VALUE.
    Missing VALUE is never estimated from close*volume.
    """
    ranked = []
    for ticker, frames in d1_payload.get("results", {}).items():
        block = frames.get("D1", {})
        if block.get("source") != OFFICIAL_D1_SOURCE or block.get("status") != "OK":
            continue
        rows = sorted(block.get("candles", []), key=lambda row: row.get("timestamp", ""))[-LIQUIDITY_LOOKBACK_SESSIONS:]
        valid = []
        for row in rows:
            value = row.get("value")
            if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
                valid.append(float(value))
        if len(valid) < LIQUIDITY_MIN_VALID_SESSIONS:
            continue
        ranked.append({
            "ticker": ticker,
            "valid_sessions": len(valid),
            "lookback_rows": len(rows),
            "average_daily_value_rub": sum(valid) / len(valid),
            "last_session": rows[-1].get("timestamp", "")[:10] if rows else None,
            "source": OFFICIAL_D1_SOURCE,
        })
    ranked.sort(key=lambda item: (-item["average_daily_value_rub"], item["ticker"]))
    return ranked[:top_n]


def collect_selected_universe(tickers, *, api_token, source_app_id=None, collector=collect_multi_timeframe):
    """Fetch D1 for all candidates, then request H1 only for the selected top 10."""
    d1_payload = collector(
        tickers, api_token=api_token, source_app_id=source_app_id, frames=("D1",)
    )
    ranking = select_top_liquid(d1_payload)
    selected = [item["ticker"] for item in ranking]
    if not selected:
        raise RuntimeError(
            "No eligible liquid shares: official MOEX ISS VALUE history must contain "
            "at least 40 valid observations in the latest 60 completed sessions."
        )
    # The collector API requires D1 alongside H1. Its second D1 response is
    # discarded; only H1 data for the selected cohort is retained.
    h1_payload = collector(
        selected, api_token=api_token, source_app_id=source_app_id, frames=("H1", "D1")
    )
    combined_results = {}
    for ticker, frames in d1_payload["results"].items():
        combined_results[ticker] = {"D1": frames.get("D1", {})}
    for ticker in selected:
        combined_results.setdefault(ticker, {})["H1"] = h1_payload["results"].get(
            ticker, {}
        ).get("H1", {"source": "Finam", "status": "ERROR", "error": "No H1 result"})
    payload = dict(d1_payload)
    payload["results"] = combined_results
    payload["universe"] = list(combined_results)
    payload["requested_frames"] = ["D1", "H1"]
    payload["liquidity_selection"] = {
        "method": "mean official MOEX ISS TQBR VALUE over latest 60 completed D1 rows",
        "minimum_valid_sessions": LIQUIDITY_MIN_VALID_SESSIONS,
        "top_n": LIQUIDITY_TOP_N,
        "candidate_count": len(tickers),
        "selected_count": len(selected),
        "ranking": ranking,
        "h1_universe": selected,
        "d1_candidate_universe": list(tickers),
        "source": OFFICIAL_D1_SOURCE,
        "missing_value_policy": "exclude missing/non-positive/non-finite VALUE; never substitute close*volume",
    }
    return payload


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
        "source_policy": "H1=Finam completed bars for top-10 liquidity cohort; D1=MOEX ISS TQBR history with official VALUE turnover for 44 candidates",
        "liquidity_selection": payload.get("liquidity_selection", {}),
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
    tickers = DEFAULT_TICKERS

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = _read_previous_state()
    payload = collect_selected_universe(
        tickers, api_token=token, source_app_id=source_app_id
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
    missing_value = sum(item.get("D1_value_missing", 0) for item in delta["symbols"].values())
    print(json.dumps({
        "status": "OK",
        "snapshot": str(output),
        "candidate_symbols": len(tickers),
        "h1_universe": payload["liquidity_selection"]["h1_universe"],
        "symbols_with_new_data": len(delta["symbols"]),
        "new_h1_bars": sum(len(item["H1"]) for item in delta["symbols"].values()),
        "new_d1_rows": sum(len(item["D1"]) for item in delta["symbols"].values()),
        "d1_rows_missing_official_value": missing_value,
        "note": "Only top-10 by official MOEX VALUE receive H1 collection; missing VALUE is never imputed.",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
