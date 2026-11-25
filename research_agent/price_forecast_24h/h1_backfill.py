"""One-off 180-calendar-day H1 backfill for all 44 MOEX shares.

Read-only Finam market-data requests only. Each request is <=30 days, matching
Finam's documented H1 history limit. Results are kept separate from LATEST.json.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_agent.multi_timeframe import (
    DEFAULT_TICKERS, RefreshingFinamClient, _finam_bar_is_complete, _serialize,
)

OUT_DIR = Path("research_agent/price_forecast_24h/data")
LOOKBACK_DAYS = 180
CHUNK_DAYS = 30


def collect_h1_backfill(tickers, *, api_token, source_app_id=None, now=None, client=None):
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if now is not None and (now.tzinfo is None or now.utcoffset() is None):
        raise ValueError("now must be timezone-aware")
    api = client or RefreshingFinamClient(api_token, source_app_id)
    start = current - timedelta(days=LOOKBACK_DAYS)
    results = {}
    for ticker in dict.fromkeys(str(x).strip().upper() for x in tickers if str(x).strip()):
        bars_by_timestamp = {}
        received_timestamps = []
        errors = []
        chunk_start = start
        while chunk_start < current:
            chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), current)
            try:
                bars = api.fetch_bars(
                    f"{ticker}@MISX", "TIME_FRAME_H1", chunk_start, chunk_end
                )
                for bar in bars:
                    received_timestamps.append(bar.timestamp.isoformat())
                    if bar.is_data_snapshot is True:
                        continue
                    if _finam_bar_is_complete(bar.timestamp, "H1", current):
                        bars_by_timestamp[bar.timestamp.isoformat()] = bar
            except Exception as exc:
                errors.append({
                    "start": chunk_start.isoformat(),
                    "end": chunk_end.isoformat(),
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                })
            chunk_start = chunk_end

        ordered = [bars_by_timestamp[k] for k in sorted(bars_by_timestamp)]
        candles = _serialize(ordered, snapshot_field=True)
        results[ticker] = {
            "source": "Finam H1",
            "status": "OK" if candles and not errors else (
                "PARTIAL" if candles else ("ERROR" if errors else "NO_DATA")
            ),
            "requested_start_utc": start.isoformat(),
            "requested_end_utc": current.isoformat(),
            "chunks_requested": (LOOKBACK_DAYS + CHUNK_DAYS - 1) // CHUNK_DAYS,
            "chunks_failed": len(errors),
            "bars": len(candles),
            "first_timestamp": candles[0]["timestamp"] if candles else None,
            "last_timestamp": candles[-1]["timestamp"] if candles else None,
            "duplicate_timestamps_removed": len(received_timestamps) - len(set(received_timestamps)),
            "errors": errors,
            "candles": candles,
        }
    return {
        "schema_version": 1,
        "generated_at_utc": current.isoformat(),
        "lookback_calendar_days": LOOKBACK_DAYS,
        "chunk_calendar_days": CHUNK_DAYS,
        "requested_symbols": list(results),
        "results": results,
        "note": "Historical research backfill; no interpolation, resampling, or trading.",
    }


def main():
    token = os.environ.get("FINAM_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("FINAM_API_TOKEN secret is required; its value is never printed")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = collect_h1_backfill(
        DEFAULT_TICKERS, api_token=token,
        source_app_id=os.environ.get("FINAM_SOURCE_APP_ID", "").strip() or None,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    output = OUT_DIR / f"h1-backfill-180d-{stamp}-{run_id}.json.gz"
    with output.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            compressed.write((json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode())
    counts = {
        status: sum(item["status"] == status for item in payload["results"].values())
        for status in ("OK", "PARTIAL", "ERROR", "NO_DATA")
    }
    print(json.dumps({
        "status": "OK" if counts["ERROR"] == 0 else "PARTIAL",
        "output": str(output),
        "symbols": len(payload["results"]),
        "status_counts": counts,
        "total_h1_bars": sum(item["bars"] for item in payload["results"].values()),
        "failed_chunks": sum(item["chunks_failed"] for item in payload["results"].values()),
        "first_timestamp": min((x["first_timestamp"] for x in payload["results"].values() if x["first_timestamp"]), default=None),
        "last_timestamp": max((x["last_timestamp"] for x in payload["results"].values() if x["last_timestamp"]), default=None),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
