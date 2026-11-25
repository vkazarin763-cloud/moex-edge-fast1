#!/usr/bin/env python3
"""Download a bounded window of free MOEX ISS 1-minute candles in parallel."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from moex_agent.config_schema import load_config
from moex_agent.moex_iss import fetch_candles
from moex_agent.storage import connect, upsert_many


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    if args.days < 5 or args.days > 90:
        parser.error("--days must be between 5 and 90")
    config = load_config(args.config)
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    start = (today - timedelta(days=args.days)).isoformat()
    end = today.isoformat()
    print(f"MOEX ISS 1-minute candles: {start} .. {end}; tickers={len(config.tickers)}")

    def fetch_one(secid: str):
        candles = fetch_candles(
            config.engine, config.market, config.board, secid,
            interval=1, from_date=start, till_date=end,
        )
        return secid, candles

    total = 0
    with connect(config.sqlite_path) as conn:
        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 12))) as pool:
            futures = [pool.submit(fetch_one, ticker) for ticker in config.tickers]
            for future in as_completed(futures):
                secid, candles = future.result()
                rows = [
                    (secid, config.board, 1, c.ts, c.open, c.high, c.low, c.close, c.value, c.volume)
                    for c in candles
                ]
                inserted = upsert_many(
                    conn, "candles",
                    ("secid", "board", "interval", "ts", "open", "high", "low", "close", "value", "volume"),
                    rows,
                )
                total += len(rows)
                first = candles[0].ts if candles else "none"
                last = candles[-1].ts if candles else "none"
                print(f"{secid}: {len(rows)} candles | {first} .. {last}")
    print(f"BOOTSTRAP_COMPLETE rows={total} tickers={len(config.tickers)}")
    return 0 if total else 2


if __name__ == "__main__":
    raise SystemExit(main())
