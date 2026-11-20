"""Manual, read-only D1↔H1 reconciliation using MOEX ISS and Finam."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .finam_crosscheck import _finam_daily_interval
from .finam_h1_crosscheck import DEFAULT_TICKERS
from .finam_market_data import FinamMarketDataClient
from .moex_iss import fetch_candles
from .timeframe_reconciliation import reconcile_moex_and_finam, reconcile_cross_source

MOSCOW = ZoneInfo("Europe/Moscow")


def _completed_h1(rows, *, now, finam):
    """Keep only fully elapsed H1 bars; preserve snapshot metadata for the report."""
    result = []
    for row in rows:
        timestamp = row.timestamp
        if timestamp.tzinfo is None:
            local = timestamp.replace(tzinfo=MOSCOW)
        else:
            local = timestamp.astimezone(MOSCOW)
        if local.astimezone(timezone.utc) + timedelta(hours=1) <= now:
            result.append(row)
    return result


def run_crosscheck(tickers, days, *, api_token, source_app_id=None, now=None):
    if not 1 <= days <= 30:
        raise ValueError("D1/H1 reconciliation lookback must be between 1 and 30 days")
    if not tickers:
        raise ValueError("At least one ticker is required")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    today_moscow = current.astimezone(MOSCOW).date()
    date_till = today_moscow - timedelta(days=1)
    date_from = today_moscow - timedelta(days=days)
    client = FinamMarketDataClient.from_api_token(api_token, source_app_id)
    finam_d1_start, finam_d1_end = _finam_daily_interval(date_from, date_till)

    results = {}
    for raw_ticker in tickers:
        ticker = raw_ticker.strip().upper()
        try:
            moex_daily = fetch_candles(
                ticker, date_from.isoformat(), date_till.isoformat(),
                interval=24, board="TQBR",
            )
            moex_hourly = fetch_candles(
                ticker, date_from.isoformat(), today_moscow.isoformat(),
                interval=60, board="TQBR",
            )
            finam_daily = client.fetch_bars(
                f"{ticker}@MISX", "TIME_FRAME_D",
                finam_d1_start, finam_d1_end,
            )
            finam_hourly = client.fetch_bars(
                f"{ticker}@MISX", "TIME_FRAME_H1",
                current - timedelta(days=days), current,
            )

            # A daily candle dated today is still forming. Finam snapshot=true
            # daily rows are also excluded; unknown metadata remains visible.
            moex_daily = [
                row for row in moex_daily
                if row.timestamp.date() < today_moscow
            ]
            finam_daily = [
                row for row in finam_daily
                if row.timestamp.astimezone(MOSCOW).date() < today_moscow
                and row.is_data_snapshot is not True
            ]
            moex_hourly = _completed_h1(
                moex_hourly, now=current, finam=False
            )
            finam_hourly = _completed_h1(
                finam_hourly, now=current, finam=True
            )
            report = reconcile_moex_and_finam(
                moex_daily=moex_daily,
                moex_hourly=moex_hourly,
                finam_daily=finam_daily,
                finam_hourly=finam_hourly,
            )
            report["cross_source"] = reconcile_cross_source(
                moex_daily=moex_daily,
                moex_hourly=moex_hourly,
                finam_daily=finam_daily,
                finam_hourly=finam_hourly,
                source_reconciliation=report,
            )
            results[ticker] = {
                "status": "COMPARED",
                "source_counts": {
                    "moex_daily_completed": len(moex_daily),
                    "moex_h1_completed": len(moex_hourly),
                    "finam_daily_completed": len(finam_daily),
                    "finam_h1_completed_raw": len(finam_hourly),
                    "finam_daily_snapshot_unknown": sum(
                        row.is_data_snapshot is None for row in finam_daily
                    ),
                },
                "reconciliation": report,
            }
        except Exception as exc:
            # Never include request headers, token values, or response bodies.
            results[ticker] = {
                "status": "SOURCE_OR_RECONCILIATION_ERROR",
                "error": str(exc),
            }

    compared = sum(item["status"] == "COMPARED" for item in results.values())
    return {
        "generated_at_utc": current.isoformat(),
        "timeframe": "D1_H1_RECONCILIATION",
        "lookback_calendar_days": days,
        "daily_date_from_inclusive": date_from.isoformat(),
        "daily_date_till_inclusive": date_till.isoformat(),
        "hourly_date_till_inclusive": today_moscow.isoformat(),
        "symbols": [f"{ticker.strip().upper()}@MISX" for ticker in tickers],
        "results": results,
        "summary": {
            "requested_symbols": len(tickers),
            "compared_symbols": compared,
            "errors": len(tickers) - compared,
        },
        "safety": (
            "Read-only market-data requests only. No account/order methods, "
            "source merging, strategy changes, holdout writes, or production access."
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Read-only MOEX/Finam D1-H1 session reconciliation"
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    parser.add_argument("--output", default="finam_moex_timeframe_reconciliation.json")
    args = parser.parse_args()
    token = os.environ.get("FINAM_API_TOKEN", "").strip()
    if not token:
        parser.error("FINAM_API_TOKEN must be supplied through the environment")
    source_app_id = os.environ.get("FINAM_SOURCE_APP_ID", "").strip() or None
    tickers = [item.strip().upper() for item in args.tickers.split(",") if item.strip()]
    report = run_crosscheck(
        tickers, args.days, api_token=token, source_app_id=source_app_id
    )
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = report["summary"]
    print(
        "D1/H1 reconciliation complete: "
        f"{summary['compared_symbols']} compared, {summary['errors']} errors; "
        f"report={args.output}"
    )
    return 0 if summary["compared_symbols"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
