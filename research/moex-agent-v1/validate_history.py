#!/usr/bin/env python3
"""Audit downloaded MOEX 1-minute candles before historical simulation."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from moex_agent.config_schema import load_config
from moex_agent.storage import connect


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    config = load_config(args.config)
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    start = (today - timedelta(days=args.days)).isoformat()
    end = today.isoformat()

    with connect(config.sqlite_path) as conn:
        df = pd.read_sql_query(
            """SELECT secid, board, ts, open, high, low, close, value, volume
               FROM candles WHERE interval=1 AND ts>=? AND ts<=?
               ORDER BY ts, secid""",
            conn, params=(start + " 00:00:00", end + " 23:59:59"),
        )
        duplicate_rows = conn.execute(
            """SELECT COUNT(*) FROM (
                 SELECT secid, board, ts FROM candles WHERE interval=1
                 GROUP BY secid, board, ts HAVING COUNT(*)>1
               )"""
        ).fetchone()[0]

    if df.empty:
        print("HISTORY_AUDIT_FAILED: no candles returned")
        return 2

    ts = pd.to_datetime(df["ts"], errors="coerce")
    numeric = df[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    missing_ohlc = int(numeric.isna().any(axis=1).sum())
    bad = (
        numeric.isna().any(axis=1)
        | (numeric <= 0).any(axis=1)
        | (numeric["high"] < numeric[["open", "close", "low"]].max(axis=1))
        | (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1))
    )
    invalid_ohlc = int(bad.sum())
    invalid_ts = int(ts.isna().sum())
    weekend = int((ts.dt.dayofweek >= 5).fillna(False).sum())
    counts = df.groupby("secid").size().to_dict()
    missing = [ticker for ticker in config.tickers if counts.get(ticker, 0) == 0]
    ready = [ticker for ticker in config.tickers if counts.get(ticker, 0) >= 200]
    summary = {
        "requested_period": {"from": start, "to": end},
        "rows": int(len(df)),
        "configured_tickers": len(config.tickers),
        "tickers_with_data": len(counts),
        "tickers_with_200plus_candles": len(ready),
        "missing_tickers": missing,
        "min_timestamp": str(df["ts"].min()),
        "max_timestamp": str(df["ts"].max()),
        "invalid_ohlc_rows": invalid_ohlc,
        "invalid_timestamp_rows": invalid_ts,
        "weekend_rows": weekend,
        "duplicate_keys": int(duplicate_rows),
        "candles_per_ticker": {k: int(v) for k, v in sorted(counts.items())},
    }
    Path("data").mkdir(exist_ok=True)
    Path("data/history_quality.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if invalid_ohlc or invalid_ts or weekend or duplicate_rows:
        print("HISTORY_AUDIT_FAILED: invalid rows, weekend data, or duplicate keys found")
        return 2
    if len(ready) < max(1, int(len(config.tickers) * 0.8)):
        print("HISTORY_AUDIT_FAILED: fewer than 80% of configured tickers have 200+ candles")
        return 2
    print("HISTORY_AUDIT_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
