"""Command-line daily research scan for the fixed MOEX first-listing universe."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .moex_iss import fetch_candles
from .validation import (walk_forward_report, adversarial_cost_check,
                         prospective_holdout_report, apply_holm_correction)
from .quality import candle_quality_report

HOLDOUT_START_DATE = "2026-11-20"  # Frozen before any prospective observations.

MOEX_FIRST_LISTING_44 = [
    "AFKS", "AFLT", "ALRS", "BSPB", "CBOM", "CHMF", "CNRU", "DOMRF",
    "ENPG", "FLOT", "GAZP", "GMKN", "HEAD", "IRAO", "LKOH", "MAGN",
    "MDMG", "MOEX", "MTSS", "NLMK", "NVTK", "OZON", "PHOR", "PLZL",
    "POSI", "RAGR", "RENI", "ROSN", "RTKM", "RUAL", "SBER", "SBERP",
    "SNGS", "SNGSP", "SVCB", "T", "TATN", "TATNP", "TRNFP", "UGLD",
    "VKCO", "VTBR", "X5", "YDEX",
]


def run_universe(date_from: str, date_till: str, tickers: list[str] | None = None) -> dict:
    selected = tickers or MOEX_FIRST_LISTING_44
    # Preserve at least three full years of pre-cutoff development history even
    # after the ordinary rolling fetch window has moved beyond the frozen date.
    minimum_history_start = date.fromisoformat(HOLDOUT_START_DATE) - timedelta(days=3 * 365 + 2)
    fetch_from = min(date.fromisoformat(date_from), minimum_history_start).isoformat()
    results = {}
    for ticker in selected:
        try:
            candles = fetch_candles(ticker, fetch_from, date_till, interval=24, board="TQBR")
            development = [
                candle for candle in candles
                if candle.timestamp.date() < date.fromisoformat(HOLDOUT_START_DATE)
            ]
            results[ticker] = {
                "status": "ANALYZED",
                "candles": len(candles),
                "first_timestamp": candles[0].timestamp.isoformat(),
                "last_timestamp": candles[-1].timestamp.isoformat(),
                "data_quality": candle_quality_report(candles, fetch_from, date_till),
                "development_period_end_exclusive": HOLDOUT_START_DATE,
                "walk_forward": walk_forward_report(development),
                "adversarial_cost_check": adversarial_cost_check(development),
                "prospective_holdout": prospective_holdout_report(
                    candles, HOLDOUT_START_DATE
                ),
            }
        except Exception as exc:
            # One failed symbol must not erase successful research for other symbols.
            results[ticker] = {"status": "DATA_OR_ANALYSIS_ERROR", "error": str(exc)}
    holdout_correction = apply_holm_correction(
        results, family_size=len(selected) * 5
    )
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "MOEX ISS public historical candles",
        "board": "TQBR",
        "interval_minutes": 24 * 60,
        "date_from": fetch_from,
        "requested_date_from": date_from,
        "date_till": date_till,
        "universe": selected,
        "development_holdout_policy": {
            "holdout_start": HOLDOUT_START_DATE,
            "holdout_is_strictly_prospective": True,
            "candidate_set_frozen": True,
            "multiple_testing_correction": holdout_correction,
        },
        "results": results,
        "safety": "Research only. No broker APIs, order placement, Telegram, or production-state writes.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only MOEX EDGE AI Research Agent")
    parser.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    parser.add_argument("--till", dest="date_till", required=True, help="YYYY-MM-DD")
    parser.add_argument("--tickers", default=",".join(MOEX_FIRST_LISTING_44),
                        help="Comma-separated tickers; defaults to the 44-symbol universe")
    parser.add_argument("--output", default="research_report.json")
    args = parser.parse_args()
    tickers = [item.strip().upper() for item in args.tickers.split(",") if item.strip()]
    report = run_universe(args.date_from, args.date_till, tickers)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    analyzed = sum(item["status"] == "ANALYZED" for item in report["results"].values())
    errors = len(report["results"]) - analyzed
    print(f"Research complete: {analyzed} analyzed, {errors} errors; report={args.output}")
    return 0 if analyzed else 1


if __name__ == "__main__":
    raise SystemExit(main())
