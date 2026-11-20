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
from .session_mapping import (earliest_session_date, latest_completed_session_date,
                              normalize_daily_candles, research_eligible_candles)

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
    history_fetch_till = (
        date.fromisoformat(calendar_date_ceiling) + timedelta(days=14)
    ).isoformat()

    history_records_by_ticker = {}
    history_errors = {}
    for ticker in selected:
        try:
            history_records_by_ticker[ticker] = fetch_history_records(
                ticker, fetch_from, history_fetch_till, board="TQBR"
            )
        except Exception as history_exc:
            history_records_by_ticker[ticker] = None
            history_errors[ticker] = str(history_exc)

    effective_till = latest_completed_session_date(
        history_records_by_ticker, calendar_date_ceiling
    ).isoformat()
    effective_from = earliest_session_date(
        history_records_by_ticker, fetch_from, effective_till
    ).isoformat()
    if requested_from > date.fromisoformat(effective_till):
        raise ValueError(
            "date_from is after the latest completed MOEX session confirmed by "
            "positive TQBR history; no completed session exists in the requested range"
        )

    results = {}
    development_candles_by_ticker = {}
    for ticker in selected:
        try:
            history_records = history_records_by_ticker[ticker]
            if history_records is None:
                raise ValueError(
                    "TQBR history unavailable for session mapping: "
                    + history_errors.get(ticker, "unknown history error")
                )
            raw_candles = fetch_candles(
                ticker, fetch_from, calendar_date_ceiling, interval=24, board="TQBR"
            )
            candles, session_mapping_diagnostics = normalize_daily_candles(
                raw_candles, history_records, max_session_date=effective_till
            )
            if not candles:
                raise ValueError("No candles remain after completed-session normalization")
            research_candles, research_eligibility = research_eligible_candles(
                candles, history_records
            )
            if not research_candles:
                raise ValueError("No research-eligible candles remain after excluding unverified weekend sessions")
            development = [
                candle for candle in research_candles
                if candle.timestamp.date() < date.fromisoformat(HOLDOUT_START_DATE)
            ]
            bounded_history_records = [
                record for record in history_records
                if record.trade_date <= date.fromisoformat(effective_till)
            ]
            try:
                history_crosscheck = audit_tqbr_history(
                    candles, bounded_history_records, fetch_from, effective_till
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
                    candles, effective_from, effective_till,
                    history_records=bounded_history_records,
                    session_date_mapping_complete=session_mapping_diagnostics[
                        "session_date_mapping_complete"
                    ],
                ),
                "session_date_mapping": session_mapping_diagnostics,
                "research_eligibility": research_eligibility,
                "research_input_bars": len(research_candles),
                "tqbr_history_crosscheck": history_crosscheck,
                "development_period_end_exclusive": HOLDOUT_START_DATE,
                "walk_forward": walk_forward_report(development),
                "adversarial_cost_check": adversarial_cost_check(development),
                "prospective_holdout": prospective_holdout_report(
                    research_candles, HOLDOUT_START_DATE
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
        "source": "MOEX ISS public historical candles and per-security TQBR daily history",
        "board": "TQBR",
        "interval_minutes": 24 * 60,
        "date_from": effective_from,
        "requested_date_from": date_from,
        "history_mapping_fetch_from": fetch_from,
        "history_mapping_fetch_till": history_fetch_till,
        "history_mapping_lookahead_days": 14,
        "date_till": effective_till,
        "requested_date_till": requested_till,
        "daily_bar_completion_policy": {
            "timezone": "Europe/Moscow",
            "maximum_requested_candle_date": calendar_date_ceiling,
            "maximum_completed_session_date": effective_till,
            "current_moscow_date_excluded": True,
            "weekend_candles_kept_on_original_dates": True,
            "weekend_session_confirmation_requires_same_date_positive_numtrades": True,
            "reason": (
                "The current Moscow calendar date is excluded. The effective end date is "
                "the latest positive-trade TQBR history date. Weekend candles at or "
                "before that cutoff remain on their original dates; same-date positive "
                "NUMTRADES confirms a weekend date. Unverified weekend bars are retained "
                "for diagnostics but excluded from all model inputs."
            ),
        },
        "session_date_policy": {
            "source": "MOEX ISS public per-security TQBR daily history",
            "weekend_mapping": (
                "No forward mapping: each weekend candle retains its original "
                "calendar date and OHLCV values."
            ),
            "same_date_confirmation": (
                "Positive same-date TQBR NUMTRADES confirms the date; otherwise "
                "the weekend candle is retained but marked unverified."
            ),
            "aggregation": "None; separate calendar dates are never merged.",
            "limitation": (
                "The subscription-only machine-readable exchange calendar is not "
                "available to this runner. Same-date TQBR history is a cross-check, "
                "not a substitute for the official calendar."
            ),
        },
        "universe": selected,
        "development_holdout_policy": {
            "holdout_start": HOLDOUT_START_DATE,
            "holdout_is_strictly_prospective": True,
            "candidate_set_frozen": True,
            "candidate_set_version": CANDIDATE_SET_VERSION,
            "multiple_testing_correction": holdout_correction,
        },
        "history_fetch_errors": history_errors,
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
