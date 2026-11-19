"""Explicit, read-only daily OHLCV comparison between MOEX ISS and Finam.

This tool does not merge the two feeds or feed Finam data into strategy tests.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .finam_market_data import FinamMarketDataClient
from .moex_iss import fetch_candles

MOSCOW = ZoneInfo("Europe/Moscow")
DEFAULT_TICKERS = ["SBER", "GAZP", "LKOH", "VTBR", "T"]


def _finam_daily_interval(start_day: date, end_day: date) -> tuple[datetime, datetime]:
    """Return UTC calendar boundaries for inclusive Finam D1 trading dates.

    Finam D1 bars are timestamped at the Moscow session's start (usually
    07:00 Moscow / 04:00 UTC). Converting Moscow midnight to UTC shifts the
    request start into the prior UTC date and can include the prior session.
    """
    return (
        datetime.combine(start_day, time.min, tzinfo=timezone.utc),
        datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=timezone.utc),
    )


def _daily_index(rows, *, finam: bool) -> dict[date, object]:
    indexed = {}
    for row in rows:
        timestamp = row.timestamp
        day = timestamp.astimezone(MOSCOW).date() if finam else timestamp.date()
        if day in indexed:
            raise ValueError(f"More than one daily candle for {day}")
        indexed[day] = row
    return indexed


def compare_daily_series(moex_rows, finam_rows) -> dict:
    """Compare daily bars by Moscow trading date; never combine source values."""
    moex = _daily_index(moex_rows, finam=False)
    finam = _daily_index(finam_rows, finam=True)
    moex_dates, finam_dates = set(moex), set(finam)
    matched_dates = sorted(moex_dates & finam_dates)
    comparisons = []

    for day in matched_dates:
        left, right = moex[day], finam[day]
        price_fields = ("open", "high", "low", "close")
        price_diffs = {}
        for field in price_fields:
            moex_value = float(getattr(left, field))
            finam_value = float(getattr(right, field))
            price_diffs[field] = {
                "moex": moex_value,
                "finam": finam_value,
                "absolute_difference": finam_value - moex_value,
                "difference_pct_of_moex": (
                    (finam_value - moex_value) / moex_value * 100.0
                ),
            }
        moex_volume = float(left.volume)
        finam_volume = float(right.volume)
        comparisons.append({
            "date": day.isoformat(),
            "prices": price_diffs,
            "volume": {
                "moex": moex_volume,
                "finam": finam_volume,
                "absolute_difference": finam_volume - moex_volume,
                "difference_pct_of_moex": (
                    (finam_volume - moex_volume) / moex_volume * 100.0
                    if moex_volume else None
                ),
            },
            "finam_is_data_snapshot": getattr(right, "is_data_snapshot", None),
        })

    if not matched_dates:
        status = "NO_OVERLAPPING_DATES"
    elif moex_dates != finam_dates:
        status = "DATE_COVERAGE_DIFFERS"
    else:
        status = "DATE_COVERAGE_MATCHES"

    return {
        "status": status,
        "comparison_basis": "daily candle date in Europe/Moscow",
        "moex_days": len(moex_dates),
        "finam_days": len(finam_dates),
        "matched_days": len(matched_dates),
        "moex_only_dates": sorted(day.isoformat() for day in moex_dates - finam_dates),
        "finam_only_dates": sorted(day.isoformat() for day in finam_dates - moex_dates),
        "comparisons": comparisons,
        "interpretation": (
            "Raw source differences only. Date coverage matching does not imply "
            "price or volume equivalence. No source is selected as truth and no "
            "values are merged."
        ),
    }


def run_crosscheck(
    tickers: list[str],
    date_from: str,
    date_till: str,
    *,
    api_token: str,
    source_app_id: str | None = None,
) -> dict:
    start_day = date.fromisoformat(date_from)
    end_day = date.fromisoformat(date_till)
    if start_day > end_day:
        raise ValueError("date_from must be on or before date_till")
    if (end_day - start_day).days + 1 > 365:
        raise ValueError("Finam D1 cross-check is limited to 365 calendar dates")
    if not tickers:
        raise ValueError("At least one ticker is required")

    client = FinamMarketDataClient.from_api_token(api_token, source_app_id)
    start_time, end_time = _finam_daily_interval(start_day, end_day)
    results = {}
    for ticker in tickers:
        symbol = f"{ticker.upper()}@MISX"
        try:
            moex_rows = fetch_candles(
                ticker, date_from, date_till, interval=24, board="TQBR"
            )
            finam_rows = client.fetch_bars(
                symbol,
                "TIME_FRAME_D",
                start_time.astimezone(timezone.utc),
                end_time.astimezone(timezone.utc),
            )
            results[ticker.upper()] = {
                "status": "COMPARED",
                "moex_candles": len(moex_rows),
                "finam_candles": len(finam_rows),
                "audit": compare_daily_series(moex_rows, finam_rows),
            }
        except Exception as exc:
            # Client exceptions are intentionally credential-safe and do not
            # include request headers, request bodies, or response payloads.
            results[ticker.upper()] = {
                "status": "SOURCE_OR_COMPARISON_ERROR",
                "error": str(exc),
            }

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "date_from_inclusive": date_from,
        "date_till_inclusive": date_till,
        "timeframe": "D1",
        "symbols": [f"{ticker.upper()}@MISX" for ticker in tickers],
        "sources": {
            "moex": "MOEX ISS TQBR daily candles",
            "finam": "Finam Trade API aggregated daily bars",
        },
        "credentials_included": False,
        "strategy_or_holdout_data_changed": False,
        "results": results,
        "safety": "Read-only market data. No account or order methods are called.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only daily MOEX ISS vs Finam candle cross-check"
    )
    parser.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    parser.add_argument("--till", dest="date_till", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--tickers", default=",".join(DEFAULT_TICKERS),
        help="Comma-separated tickers; defaults to SBER,GAZP,LKOH,VTBR,T",
    )
    parser.add_argument("--output", default="finam_moex_crosscheck.json")
    args = parser.parse_args()

    api_token = os.environ.get("FINAM_API_TOKEN", "").strip()
    if not api_token:
        parser.error("FINAM_API_TOKEN must be supplied through the environment")
    source_app_id = os.environ.get("FINAM_SOURCE_APP_ID", "").strip() or None
    tickers = [item.strip().upper() for item in args.tickers.split(",") if item.strip()]
    report = run_crosscheck(
        tickers, args.date_from, args.date_till,
        api_token=api_token, source_app_id=source_app_id,
    )
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    compared = sum(item["status"] == "COMPARED" for item in report["results"].values())
    errors = len(report["results"]) - compared
    print(f"Finam/MOEX cross-check complete: {compared} compared, {errors} errors; report={args.output}")
    return 0 if compared else 1


if __name__ == "__main__":
    raise SystemExit(main())
