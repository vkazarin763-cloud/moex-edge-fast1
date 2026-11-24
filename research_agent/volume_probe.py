"""Read-only cross-timeframe volume probe for known MOEX ISS discrepancies.

This compares public /iss 1-minute candles with daily /iss candles. It is a
cross-timeframe consistency check, not an independent exchange data vendor:
both responses originate from MOEX ISS. It never changes research inputs.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

from .moex_iss import ISSDataError, fetch_candles

CASES_PATH = Path(__file__).with_name("volume_probe_cases.json")


def _same_number(left: float, right: float, *, rel_tol: float = 1e-9) -> bool:
    return math.isclose(left, right, rel_tol=rel_tol, abs_tol=1e-8)


def probe_case(case: dict, *, fetcher=fetch_candles) -> dict:
    ticker = str(case["ticker"]).strip().upper()
    trade_date = date.fromisoformat(case["trade_date"])
    result = {
        "ticker": ticker,
        "trade_date": trade_date.isoformat(),
        "source": "MOEX ISS /iss candles; interval=1 vs interval=24",
        "baseline_run_id": 45378870392,
        "status": "NOT_CHECKED",
    }
    try:
        daily_rows = [
            row for row in fetcher(
                ticker, trade_date.isoformat(), trade_date.isoformat(),
                interval=24, board="TQBR",
            )
            if row.timestamp.date() == trade_date
        ]
        try:
            fetched_minutes = fetcher(
                ticker, trade_date.isoformat(), trade_date.isoformat(),
                interval=1, board="TQBR",
            )
        except ISSDataError as exc:
            if "No candles returned" not in str(exc):
                raise
            fetched_minutes = []
        minute_rows = [
            row for row in fetched_minutes if row.timestamp.date() == trade_date
        ]
        if len(daily_rows) != 1:
            raise ISSDataError(
                f"Expected exactly one daily candle for {trade_date}; got {len(daily_rows)}"
            )
        if not minute_rows:
            result.update({
                "status": "NO_MINUTE_CANDLES",
                "daily_volume": daily_rows[0].volume,
                "minute_candle_count": 0,
            })
            return result

        daily = daily_rows[0]
        minute_ohlcv = {
            "open": minute_rows[0].open,
            "high": max(row.high for row in minute_rows),
            "low": min(row.low for row in minute_rows),
            "close": minute_rows[-1].close,
            "volume": sum(row.volume for row in minute_rows),
        }
        ohlc_match = all(_same_number(minute_ohlcv[key], getattr(daily, key))
                         for key in ("open", "high", "low", "close"))
        volume_match = _same_number(minute_ohlcv["volume"], daily.volume)
        result.update({
            "status": "CROSS_TIMEFRAME_MATCH" if ohlc_match and volume_match
                      else "CROSS_TIMEFRAME_MISMATCH",
            "daily_ohlcv": {
                "open": daily.open, "high": daily.high, "low": daily.low,
                "close": daily.close, "volume": daily.volume,
            },
            "minute_aggregate_ohlcv": minute_ohlcv,
            "minute_candle_count": len(minute_rows),
            "first_minute": minute_rows[0].timestamp.isoformat(),
            "last_minute": minute_rows[-1].timestamp.isoformat(),
            "ohlc_matches_daily": ohlc_match,
            "volume_matches_daily": volume_match,
            "volume_difference_minute_minus_daily":
                minute_ohlcv["volume"] - daily.volume,
            "volume_matches_frozen_raw_baseline":
                _same_number(minute_ohlcv["volume"], float(case["raw_volume"])),
            "volume_matches_total_session_history":
                _same_number(minute_ohlcv["volume"], float(case["total_session_history_volume"])),
            "volume_matches_morning_plus_main_history":
                _same_number(minute_ohlcv["volume"], float(case["morning_plus_main_history_volume"])),
            "frozen_baseline": {
                "raw_daily_volume": case["raw_volume"],
                "total_session_history_volume": case["total_session_history_volume"],
                "morning_plus_main_history_volume": case["morning_plus_main_history_volume"],
            },
            "interpretation_limit":
                "MOEX /iss interval=1 and interval=24 are same-provider cross-checks, "
                "not independent proof of the exchange's authoritative volume.",
        })
        return result
    except Exception as exc:
        result.update({
            "status": "FETCH_OR_VALIDATION_ERROR",
            "error": f"{type(exc).__name__}: {exc}",
        })
        return result


def run_probe(cases: list[dict] | None = None, *, fetcher=fetch_candles) -> dict:
    if cases is None:
        payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        cases = payload["cases"]
    results = [probe_case(case, fetcher=fetcher) for case in cases]
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "schema_version": "moex-iss-cross-timeframe-volume-probe-v1",
        "read_only": True,
        "baseline_run_id": 45378870392,
        "source_limitations": [
            "Only public MOEX ISS /iss candles are queried.",
            "No /iss/history subscriber-only endpoint is queried.",
            "This is not an independent vendor or trade-by-trade reconciliation.",
            "Probe results do not modify scanner data or clear existing warnings.",
        ],
        "case_count": len(results),
        "status_counts": counts,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="moex_iss_volume_probe.json")
    args = parser.parse_args()
    report = run_probe()
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": args.output,
        "case_count": report["case_count"],
        "status_counts": report["status_counts"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
