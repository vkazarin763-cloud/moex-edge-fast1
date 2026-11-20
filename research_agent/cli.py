"""Command-line daily research scan for the fixed MOEX first-listing universe."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .moex_iss import fetch_candles, fetch_history_records
from .validation import (walk_forward_report, adversarial_cost_check,
                         prospective_holdout_report, apply_holm_correction, CANDIDATE_SET_VERSION)
from .quality import candle_quality_report, audit_tqbr_history
from .portfolio import walk_forward_portfolio_report
from .session_calendar import (fetch_stock_calendar, latest_completed_session_date,
                              normalize_daily_candles)

HOLDOUT_START_DATE = "2026-11-20"  # Frozen before any prospective observations.

MOEX_TIMEZONE = ZoneInfo("Europe/Moscow")


def cap_to_last_completed_moscow_date(
    requested_till: str, now: datetime | None = None,
) -> str:
    """Never include today's potentially unfinished MOEX daily candle."""
    requested_date = date.fromisoformat(requested_till)
    if now is not None and (now.tzinfo is None or now.utcoffset() is None):
        raise ValueError("now must be timezone-aware")
    local_now = now.astimezone(MOEX_TIMEZONE) if now is not None else datetime.now(MOEX_TIMEZONE)
    last_completed_date = local_now.date() - timedelta(days=1)
    return min(requested_date, last_completed_date).isoformat()


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
    requested_till = date.fromisoformat(date_till).isoformat()
    calendar_date_ceiling = cap_to_last_completed_moscow_date(requested_till)
    requested_from = date.fromisoformat(date_from)
    minimum_history_start = date.fromisoformat(HOLDOUT_START_DATE) - timedelta(days=3 * 365 + 2)
    fetch_from = min(requested_from, minimum_history_start).isoformat()
    calendar_fetch_till = (
        date.fromisoformat(calendar_date_ceiling) + timedelta(days=7)
    ).isoformat()
    stock_calendar = fetch_stock_calendar(fetch_from, calendar_fetch_till)
    effective_till = latest_completed_session_date(
        stock_calendar, calendar_date_ceiling
    ).isoformat()
    if requested_from > date.fromisoformat(effective_till):
        raise ValueError(
            "date_from is after the latest completed MOEX trading-session date; "
            "unfinished current-day and weekend-linked sessions are excluded"
        )
    results = {}
    development_candles_by_ticker = {}
    for ticker in selected:
        try:
            raw_candles = fetch_candles(
                ticker, fetch_from, calendar_date_ceiling, interval=24, board="TQBR"
            )
            candles, session_calendar_diagnostics = normalize_daily_candles(
                raw_candles, stock_calendar, max_session_date=effective_till
            )
            if not candles:
                raise ValueError("No candles remain after completed-session normalization")
            development = [
                candle for candle in candles
                if candle.timestamp.date() < date.fromisoformat(HOLDOUT_START_DATE)
            ]
            history_records = None
            try:
                history_records = fetch_history_records(
                    ticker, fetch_from, effective_till, board="TQBR"
                )
                history_crosscheck = audit_tqbr_history(
                    candles, history_records, fetch_from, effective_till
                )
            except Exception as history_exc:
                history_crosscheck = {
                    "status": "HISTORY_CROSSCHECK_UNAVAILABLE",
                    "error": str(history_exc),
                    "exchange_calendar_verified": False,
                }
            results[ticker] = {
                "status": "ANALYZED",
                "candles": len(candles),
                "first_timestamp": candles[0].timestamp.isoformat(),
                "last_timestamp": candles[-1].timestamp.isoformat(),
                "data_quality": candle_quality_report(
                    candles, fetch_from, effective_till,
                    history_records=history_records,
                ),
                "session_calendar_aggregation": session_calendar_diagnostics,
                "tqbr_history_crosscheck": history_crosscheck,
                "development_period_end_exclusive": HOLDOUT_START_DATE,
                "walk_forward": walk_forward_report(development),
                "adversarial_cost_check": adversarial_cost_check(development),
                "prospective_holdout": prospective_holdout_report(
                    candles, HOLDOUT_START_DATE
                ),
            }
            development_candles_by_ticker[ticker] = development
        except Exception as exc:
            results[ticker] = {"status": "DATA_OR_ANALYSIS_ERROR", "error": str(exc)}
    holdout_correction = apply_holm_correction(
        results, family_size=len(selected) * 5
    )
    try:
        development_portfolio = walk_forward_portfolio_report(
            development_candles_by_ticker,
            folds=4,
            warmup_bars=200,
        ) if development_candles_by_ticker else {
            "status": "NO_DEVELOPMENT_DATA",
            "warning": "No ticker supplied usable development candles.",
        }
    except ValueError as exc:
        development_portfolio = {
            "status": "INSUFFICIENT_DEVELOPMENT_DATA",
            "reason": str(exc),
            "warning": "No portfolio metrics were calculated.",
        }
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "MOEX ISS public historical candles and TQBR daily history",
        "board": "TQBR",
        "interval_minutes": 24 * 60,
        "date_from": fetch_from,
        "requested_date_from": date_from,
        "date_till": effective_till,
        "requested_date_till": requested_till,
        "daily_bar_completion_policy": {
            "timezone": "Europe/Moscow",
            "maximum_requested_candle_date": calendar_date_ceiling,
            "maximum_completed_session_date": effective_till,
            "current_moscow_date_excluded": True,
            "weekend_linked_sessions_excluded_until_their_target_session_completes": True,
            "reason": (
                "The current daily candle is excluded. Weekend sessions are assigned "
                "to the official MOEX trade_session_date and included only after that "
                "target session has completed."
            ),
        },
        "calendar_session_policy": {
            "source": "MOEX ISS stock calendar",
            "weekend_reason_code": "W",
            "mapping_field": "trade_session_date",
            "aggregation": "Chronological first open, maximum high, minimum low, last close, summed volume",
            "purpose": "One indicator/backtest bar per official MOEX trading session",
        },
        "universe": selected,
        "development_holdout_policy": {
            "holdout_start": HOLDOUT_START_DATE,
            "holdout_is_strictly_prospective": True,
            "candidate_set_frozen": True,
            "candidate_set_version": CANDIDATE_SET_VERSION,
            "multiple_testing_correction": holdout_correction,
        },
        "results": results,
        "development_portfolio": development_portfolio,
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
