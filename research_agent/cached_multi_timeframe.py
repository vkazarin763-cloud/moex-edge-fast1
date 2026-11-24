"""Incremental, validated Finam candle cache for the read-only D1/H1 pipeline.

The cache contains public market bars only. It never stores credentials or account data.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .finam_market_data import FinamBar
from .multi_timeframe import (
    DEFAULT_TICKERS, FINAM_FRAMES, RefreshingFinamClient, collect_multi_timeframe,
)

CACHE_SCHEMA_VERSION = 1
FRAME_OVERLAP = {
    "TIME_FRAME_D": timedelta(days=3),
    "TIME_FRAME_H1": timedelta(hours=3),
}
FRAME_RETENTION = {
    "TIME_FRAME_D": timedelta(days=365),
    "TIME_FRAME_H1": timedelta(days=30),
}


def _bar_to_dict(bar: FinamBar) -> dict:
    return {
        "timestamp": bar.timestamp.astimezone(timezone.utc).isoformat(),
        "open": float(bar.open), "high": float(bar.high),
        "low": float(bar.low), "close": float(bar.close),
        "volume": float(bar.volume),
        "is_data_snapshot": bar.is_data_snapshot,
    }


def _dict_to_bar(item: dict) -> FinamBar:
    stamp = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Cached Finam timestamp must include a timezone")
    return FinamBar(
        stamp.astimezone(timezone.utc),
        float(item["open"]), float(item["high"]), float(item["low"]),
        float(item["close"]), float(item["volume"]),
        item.get("is_data_snapshot"),
    )


def load_cache(path: str | Path) -> dict:
    cache_path = Path(path)
    if not cache_path.exists():
        return {"schema_version": CACHE_SCHEMA_VERSION, "bars": {}}
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
            return {"schema_version": CACHE_SCHEMA_VERSION, "bars": {}}
        if not isinstance(payload.get("bars"), dict):
            raise ValueError("Cache bars field must be an object")
        # Parse every row now; a corrupt cache must not contaminate a scan.
        for symbols in payload["bars"].values():
            if not isinstance(symbols, dict):
                raise ValueError("Cache symbol entry must be an object")
            for rows in symbols.values():
                if not isinstance(rows, list):
                    raise ValueError("Cache timeframe entry must be an array")
                for row in rows:
                    _dict_to_bar(row)
        return payload
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        # A damaged cache is discarded safely; the next API request performs
        # the normal full lookback rather than trusting partial/corrupt rows.
        return {"schema_version": CACHE_SCHEMA_VERSION, "bars": {}}


def save_cache(path: str | Path, cache: dict) -> None:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "bars": cache.get("bars", {}),
    }
    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(cache_path)


class CachedFinamClient:
    """Wrap the read-only client with overlap refresh and timestamp deduplication."""

    def __init__(self, client, cache: dict, *, full_refresh: bool = False):
        self.client = client
        self.cache = cache
        self.full_refresh = full_refresh
        self.stats = {"cache_hits": 0, "incremental_requests": 0,
                      "full_requests": 0, "bars_reused": 0,
                      "bars_fetched": 0, "overlap_corrections": 0}

    def fetch_bars(self, symbol, timeframe, start, end):
        symbol = symbol.strip().upper()
        symbol_cache = self.cache.setdefault("bars", {}).setdefault(symbol, {})
        cached_rows = symbol_cache.get(timeframe, [])
        cached = [_dict_to_bar(row) for row in cached_rows]
        request_start = start
        if cached and not self.full_refresh:
            latest = max(bar.timestamp for bar in cached)
            overlap_start = latest - FRAME_OVERLAP.get(timeframe, timedelta(hours=1))
            request_start = max(start, overlap_start)
            self.stats["cache_hits"] += 1
            self.stats["incremental_requests"] += 1
            self.stats["bars_reused"] += len(cached)
        else:
            self.stats["full_requests"] += 1

        fresh = self.client.fetch_bars(symbol, timeframe, request_start, end)
        self.stats["bars_fetched"] += len(fresh)
        merged = {bar.timestamp: bar for bar in cached if start <= bar.timestamp < end}
        for bar in fresh:
            if bar.timestamp in merged and _bar_to_dict(merged[bar.timestamp]) != _bar_to_dict(bar):
                self.stats["overlap_corrections"] += 1
            merged[bar.timestamp] = bar

        retention_start = end - FRAME_RETENTION.get(timeframe, timedelta(days=365))
        result = [
            bar for stamp, bar in sorted(merged.items())
            if retention_start <= stamp < end
        ]
        symbol_cache[timeframe] = [_bar_to_dict(bar) for bar in result]
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Incremental read-only Finam D1/H1 collection")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    parser.add_argument("--frames", default="D1,H1")
    parser.add_argument("--output", default="moex_edge_multi_timeframe_candles.json")
    parser.add_argument("--cache", default=".cache/moex-edge-finam-candles.json")
    parser.add_argument("--full-refresh", action="store_true",
                        help="Ignore cached bars and rebuild the requested Finam lookback.")
    args = parser.parse_args()

    token = os.environ.get("FINAM_API_TOKEN", "").strip()
    if not token:
        parser.error("FINAM_API_TOKEN must be supplied through the environment")
    source_app_id = os.environ.get("FINAM_SOURCE_APP_ID", "").strip() or None
    frames = [item.strip().upper() for item in args.frames.split(",") if item.strip()]
    unsupported = set(frames) - set(FINAM_FRAMES)
    if unsupported:
        parser.error(f"Incremental cache currently supports Finam frames only: {sorted(unsupported)}")
    cache = load_cache(args.cache)
    client = CachedFinamClient(
        RefreshingFinamClient(token, source_app_id), cache,
        full_refresh=args.full_refresh,
    )
    tickers = [item.strip().upper() for item in args.tickers.split(",") if item.strip()]
    report = collect_multi_timeframe(
        tickers, api_token=token, source_app_id=source_app_id,
        frames=frames, finam_client=client,
    )
    save_cache(args.cache, cache)
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print("Incremental Finam collection complete:")
    for frame, values in report["timeframes"].items():
        print(
            f"{frame}: {values['ok']}/{values['symbols']} symbols, "
            f"{values['total_completed_bars']} completed bars, {values['errors']} errors"
        )
    print("Cache diagnostics: " + json.dumps(client.stats, sort_keys=True))
    print(f"Cache saved: {args.cache}")
    return 0 if all(value["ok"] == value["symbols"] and value["errors"] == 0
                    for value in report["timeframes"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
