"""Command-line daily research scan for the fixed MOEX first-listing universe."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .moex_iss import fetch_candles
from .validation import walk_forward_report, adversarial_cost_check
from .quality import candle_quality_report

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
    results = {}
    for ticker in selected:
        try:
            candles = fetch_candles(ticker, date_from, date_till, interval=24, board="TQBR")
            results[ticker] = {
                "status": "ANALYZED",
                "candles": len(candles),
                "first_timestamp": candles[0].timestamp.isoformat(),
                "last_timestamp": candles[-1].timestamp.isoformat(),
                "data_quality": candle_quality_report(candles, date_from, date_till),
                "walk_forward": walk_forward_report(candles),
                "adversarial_cost_check": adversarial_cost_check(candles),
            }
        except Exception as exc:
            # One failed symbol must not erase successful research for other symbols.
            results[ticker] = {"status": "DATA_OR_ANALYSIS_ERROR", "error": str(exc)}
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "MOEX ISS public historical candles",
        "board": "TQBR",
        "interval_minutes": 24 * 60,
        "date_from": date_from,
        "date_till": date_till,
        "universe": selected,
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
