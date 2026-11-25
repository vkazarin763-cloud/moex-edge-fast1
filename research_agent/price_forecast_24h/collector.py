"""Prospective, read-only collector for all 44 MOEX candidate shares."""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_agent.multi_timeframe import (DEFAULT_TICKERS, RefreshingFinamClient, _finam_bar_is_complete, _serialize)

DATA_DIR = Path("research_agent/price_forecast_24h/data")
STATE_FILE = DATA_DIR / "LATEST.json"
H1_HISTORY_FILE = DATA_DIR / "H1_HISTORY.json.gz"


def collect_incremental_h1(
    tickers, *, history, api_token, source_app_id=None, now=None, client=None
):
    """Fetch only the interval since each symbol's latest stored H1 candle."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    api = client or RefreshingFinamClient(api_token, source_app_id)
    results = {}
    for ticker in dict.fromkeys(str(t).strip().upper() for t in tickers if str(t).strip()):
        stored = history.get("symbols", {}).get(ticker, {}).get("candles", [])
        last_timestamp = stored[-1]["timestamp"] if stored else ""
        if last_timestamp:
            last_dt = datetime.fromisoformat(last_timestamp)
            # One-bar overlap protects API boundaries; cumulative merge deduplicates it.
            start = max(last_dt - timedelta(hours=1), current - timedelta(days=30))
        else:
            start = current - timedelta(days=30)
        try:
            raw = api.fetch_bars(f"{ticker}@MISX", "TIME_FRAME_H1", start, current)
            completed = [
                bar for bar in raw
                if bar.is_data_snapshot is not True
                and _finam_bar_is_complete(bar.timestamp, "H1", current)
            ]
            all_candles = _serialize(completed, snapshot_field=True)
            new_candles = [
                row for row in all_candles
                if not last_timestamp or row["timestamp"] > last_timestamp
            ]
            results[ticker] = {"H1": {
                "source": "Finam", "status": "OK",
                "requested_start_utc": start.isoformat(),
                "raw_bars": len(raw), "completed_bars": len(completed),
                "new_bars": len(new_candles), "candles": new_candles,
            }}
        except Exception as exc:
            results[ticker] = {"H1": {
                "source": "Finam", "status": "ERROR",
                "requested_start_utc": start.isoformat(), "candles": [],
                "error": f"{type(exc).__name__}: {exc}"[:500],
            }}
    return {
        "generated_at_utc": current.isoformat(), "timezone": "UTC",
        "results": results,
        "universe_selection": {
            "method": "fixed complete 44-symbol universe; no liquidity filter",
            "candidate_count": len(results), "selected_count": len(results),
            "symbols": list(results), "liquidity_filter": "disabled",
        },
    }


def _read_previous_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read previous collector state: {exc}") from exc


def _latest_h1_by_symbol(state: dict) -> dict[str, str]:
    value = state.get("latest_h1", {})
    return value if isinstance(value, dict) else {}


def build_daily_delta(payload: dict, state: dict) -> tuple[dict, dict]:
    """Keep only newly completed H1 bars; never fill gaps."""
    previous_h1 = _latest_h1_by_symbol(state)
    delta = {
        "schema_version": 1,
        "generated_at_utc": payload["generated_at_utc"],
        "timezone": payload["timezone"],
        "source_policy": "Incremental Finam H1 completed bars; all 44 symbols retained without liquidity filtering",
        "universe_selection": payload.get("universe_selection", {}),
        "symbols": {},
    }
    next_h1 = dict(previous_h1)
    for ticker, frames in payload["results"].items():
        block = frames.get("H1", {})
        candles = block.get("candles", [])
        last_seen = previous_h1.get(ticker, "")
        new_bars = [row for row in candles if row["timestamp"] > last_seen]
        if new_bars or block.get("status") != "OK":
            delta["symbols"][ticker] = {
                "H1": new_bars,
                "H1_source": block.get("source"),
                "H1_status": block.get("status"),
                "H1_error": block.get("error"),
            }
        if new_bars:
            next_h1[ticker] = max(row["timestamp"] for row in new_bars)
    state_out = {
        "schema_version": 1,
        "latest_h1": next_h1,
        "updated_at_utc": payload["generated_at_utc"],
    }
    return delta, state_out


def _read_h1_history() -> dict:
    """Load cumulative H1 history, seeding it from the one-time backfill."""
    if H1_HISTORY_FILE.exists():
        try:
            with gzip.open(H1_HISTORY_FILE, "rt", encoding="utf-8") as stream:
                return json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot read cumulative H1 history: {exc}") from exc

    history = {"schema_version": 1, "source": "Finam H1", "symbols": {}}
    archives = sorted(DATA_DIR.glob("h1-backfill-180d-*.json.gz"))
    if archives:
        with gzip.open(archives[-1], "rt", encoding="utf-8") as stream:
            initial = json.load(stream)
        for ticker, block in initial.get("results", {}).items():
            candles = block.get("candles", [])
            history["symbols"][ticker] = {
                "candles": candles,
                "first_timestamp": candles[0]["timestamp"] if candles else None,
                "last_timestamp": candles[-1]["timestamp"] if candles else None,
            }
    return history


def merge_cumulative_h1(delta: dict, history: dict) -> dict:
    """Append only new H1 candles and deduplicate by timestamp."""
    symbols = history.setdefault("symbols", {})
    for ticker, block in delta.get("symbols", {}).items():
        current = symbols.setdefault(ticker, {"candles": []})
        by_time = {row["timestamp"]: row for row in current.get("candles", [])}
        for row in block.get("H1", []):
            by_time.setdefault(row["timestamp"], row)
        candles = [by_time[key] for key in sorted(by_time)]
        current["candles"] = candles
        current["first_timestamp"] = candles[0]["timestamp"] if candles else None
        current["last_timestamp"] = candles[-1]["timestamp"] if candles else None
    history["updated_at_utc"] = delta.get("generated_at_utc")
    history["symbols"] = dict(sorted(symbols.items()))
    return history


def _write_h1_history(history: dict) -> None:
    temporary = DATA_DIR / "H1_HISTORY.tmp"
    with temporary.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            payload = json.dumps(history, ensure_ascii=False, sort_keys=True) + "\n"
            compressed.write(payload.encode("utf-8"))
    temporary.replace(H1_HISTORY_FILE)

def main() -> None:
    token = os.environ.get("FINAM_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("FINAM_API_TOKEN secret is required; its value is never printed")
    source_app_id = os.environ.get("FINAM_SOURCE_APP_ID", "").strip() or None
    tickers = DEFAULT_TICKERS

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = _read_previous_state()
    h1_history = _read_h1_history()
    payload = collect_incremental_h1(
        tickers, history=h1_history, api_token=token, source_app_id=source_app_id
    )
    delta, state_out = build_daily_delta(payload, state)
    h1_history = merge_cumulative_h1(delta, h1_history)
    _write_h1_history(h1_history)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    output = DATA_DIR / f"snapshot-{stamp}-{run_id}.json.gz"
    if output.exists():
        raise SystemExit(f"Snapshot already exists for this run; refusing to overwrite: {output}")
    with output.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            compressed.write((json.dumps(delta, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    STATE_FILE.write_text(json.dumps(state_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    statuses = {
        "ok": sum(v.get("H1", {}).get("status") == "OK" for v in payload["results"].values()),
        "errors": sum(v.get("H1", {}).get("status") == "ERROR" for v in payload["results"].values()),
    }
    print(json.dumps({
        "status": "OK" if statuses["errors"] == 0 else "PARTIAL",
        "snapshot": str(output),
        "requested_symbols": len(tickers),
        "symbols_returned": len(payload["results"]),
        "symbols_with_new_data": sum(bool(v.get("H1", {}).get("candles")) for v in payload["results"].values()),
        "new_h1_bars": sum(len(item["H1"]) for item in delta["symbols"].values()),
        "cumulative_h1_bars": sum(len(item.get("candles", [])) for item in h1_history["symbols"].values()),
        "cumulative_h1_symbols": len(h1_history["symbols"]),
        "frame_status": {"H1": statuses},
        "note": "Only bars after the latest stored timestamp are requested; a one-bar overlap is deduplicated. No trading.",
    }, ensure_ascii=False))




if __name__ == "__main__":
    main()
