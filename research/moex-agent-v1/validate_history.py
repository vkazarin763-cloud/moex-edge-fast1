#!/usr/bin/env python3
"""Audit and sanitize MOEX ISS 1-minute candles for weekday trading-session backtests.

MOEX ISS timestamps are treated as Moscow local time (naive exchange timestamps).
Weekend technical rows and malformed/out-of-session rows are reported and removed
from the isolated paper database before the backtest. Raw counts remain in the
quality report so exclusions are transparent.
"""
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
        invalid_mask = (
            ts.isna()
            | numeric.isna().any(axis=1)
            | (numeric <= 0).any(axis=1)
            | (numeric["high"] < numeric[["open", "close", "low"]].max(axis=1))
            | (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1))
        )
        weekend_mask = ts.dt.dayofweek.ge(5).fillna(False)
        minutes = ts.dt.hour * 60 + ts.dt.minute
        # Include MOEX equity morning, main and evening sessions (Moscow time).
        outside_session_mask = ts.notna() & ((minutes < 6 * 60 + 50) | (minutes > 23 * 60 + 50))
        exclude_mask = invalid_mask | weekend_mask | outside_session_mask

        invalid_count = int(invalid_mask.sum())
        weekend_count = int(weekend_mask.sum())
        outside_count = int(outside_session_mask.sum())
        invalid_timestamp_count = int(ts.isna().sum())

        # Remove excluded rows from the disposable paper DB, never from source data.
        excluded = df.loc[exclude_mask, ["secid", "board", "ts"]].drop_duplicates()
        conn.execute("CREATE TEMP TABLE excluded_candles (secid TEXT, board TEXT, ts TEXT, PRIMARY KEY(secid, board, ts))")
        conn.executemany(
            "INSERT OR IGNORE INTO excluded_candles(secid, board, ts) VALUES (?, ?, ?)",
            excluded.itertuples(index=False, name=None),
        )
        conn.execute(
            """DELETE FROM candles
               WHERE interval=1 AND EXISTS (
                 SELECT 1 FROM excluded_candles x
                 WHERE x.secid=candles.secid AND x.board=candles.board AND x.ts=candles.ts
               )"""
        )
        conn.commit()

        clean = df.loc[~exclude_mask].copy()
        clean_counts = clean.groupby("secid").size().to_dict()
        missing = [ticker for ticker in config.tickers if clean_counts.get(ticker, 0) == 0]
        ready = [ticker for ticker in config.tickers if clean_counts.get(ticker, 0) >= 200]
        remaining = conn.execute(
            """SELECT COUNT(*) FROM candles WHERE interval=1 AND ts>=? AND ts<=?""",
            (start + " 00:00:00", end + " 23:59:59"),
        ).fetchone()[0]

    summary = {
        "requested_period": {"from": start, "to": end},
        "raw_rows": int(len(df)),
        "clean_rows": int(remaining),
        "excluded_rows": int(exclude_mask.sum()),
        "configured_tickers": len(config.tickers),
        "tickers_with_clean_data": len(clean_counts),
        "tickers_with_200plus_clean_candles": len(ready),
        "missing_tickers_after_cleaning": missing,
        "raw_min_timestamp": str(df["ts"].min()),
        "raw_max_timestamp": str(df["ts"].max()),
        "invalid_ohlc_rows_excluded": invalid_count,
        "invalid_timestamp_rows_excluded": invalid_timestamp_count,
        "weekend_rows_excluded": weekend_count,
        "outside_moex_session_rows_excluded": outside_count,
        "duplicate_keys_before_cleaning": int(duplicate_rows),
        "session_policy": "Weekdays only; 06:50-23:50 Moscow time; malformed OHLC excluded.",
        "candles_per_ticker_after_cleaning": {k: int(v) for k, v in sorted(clean_counts.items())},
    }
    Path("data").mkdir(exist_ok=True)
    Path("data/history_quality.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if duplicate_rows:
        print("HISTORY_AUDIT_FAILED: duplicate candle keys found")
        return 2
    if len(ready) < max(1, int(len(config.tickers) * 0.8)):
        print("HISTORY_AUDIT_FAILED: fewer than 80% of configured tickers have 200+ clean candles")
        return 2
    if invalid_count or weekend_count or outside_count:
        print("HISTORY_AUDIT_CLEANED: excluded rows are documented; clean dataset passed structural checks")
    print("HISTORY_AUDIT_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
