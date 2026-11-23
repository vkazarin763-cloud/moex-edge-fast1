"""Command-line daily research scan for the fixed MOEX first-listing universe."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .moex_iss import fetch_candles, fetch_history_records
from .corporate_actions import apply_post_event_price_basis
from .validation import (walk_forward_report, adversarial_cost_check,
                         prospective_holdout_report, apply_holm_correction, CANDIDATE_SET_VERSION,
                         cross_sectional_direction_summary)
from .quality import candle_quality_report, audit_tqbr_history
from .portfolio import walk_forward_portfolio_report
from .independent_validator import validate_research_report
from .experiment_lab import run_experiment_lab
from .strategy_registry import build_strategy_registry
from .session_mapping import (
    earliest_session_date, latest_completed_session_date,
    build_trading_day_candles, reconcile_session_candles,
    combine_morning_main_history_records,
)

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


def run_universe(
    date_from: str,
    date_till: str,
    tickers: list[str] | None = None,
    *,
    run_experiment_lab_enabled: bool = False,
) -> dict:
    selected = tickers or MOEX_FIRST_LISTING_44
    requested_till = date.fromisoformat(date_till).isoformat()
    calendar_date_ceiling = cap_to_last_completed_moscow_date(requested_till)
    requested_from = date.fromisoformat(date_from)
    minimum_history_start = date.fromisoformat(HOLDOUT_START_DATE) - timedelta(days=3 * 365 + 2)
    fetch_from = min(requested_from, minimum_history_start).isoformat()
    history_fetch_till = calendar_date_ceiling

    history_records_by_ticker = {}
    history_errors = {}
    # T traded as TCSG through 2024-11-27. Fetch that retired code only as
    # auxiliary evidence for raw-candle reconciliation; the model input remains
    # the current T security's own TQBR history.
    legacy_reconciliation_history_by_ticker = {}
    legacy_history_errors = {}
    for ticker in selected:
        try:
            history_records_by_ticker[ticker] = fetch_history_records(
                ticker, fetch_from, history_fetch_till, board="TQBR"
            )
        except Exception as history_exc:
            history_records_by_ticker[ticker] = None
            history_errors[ticker] = str(history_exc)
        if ticker == "T" and history_records_by_ticker[ticker] is not None:
            legacy_till = min(history_fetch_till, "2024-11-27")
            if fetch_from <= legacy_till:
                try:
                    legacy_reconciliation_history_by_ticker[ticker] = fetch_history_records(
                        "TCSG", fetch_from, legacy_till, board="TQBR"
                    )
                except Exception as alias_exc:
                    legacy_reconciliation_history_by_ticker[ticker] = []
                    legacy_history_errors[ticker] = str(alias_exc)

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
            raw_candle_fetch_error = None
            try:
                raw_candles = fetch_candles(
                    ticker, fetch_from, calendar_date_ceiling, interval=24, board="TQBR"
                )
            except Exception as raw_exc:
                raw_candles = []
                raw_candle_fetch_error = str(raw_exc)
            bounded_history_records = [
                record for record in history_records
                if record.trade_date <= date.fromisoformat(effective_till)
            ]
            comparison_history_error = None
            comparison_history_records = None
            reconciliation_history_records = list(bounded_history_records)
            legacy_alias = None
            if ticker == "T" and ticker in legacy_reconciliation_history_by_ticker:
                legacy_alias = {
                    "ticker": "TCSG",
                    "through": "2024-11-27",
                    "source": "MOEX ISS TQBR history; MOEX ticker change effective 2024-11-28",
                    "used_for_model_input": False,
                }
                reconciliation_history_records.extend(
                    record for record in legacy_reconciliation_history_by_ticker[ticker]
                    if date.fromisoformat(effective_from)
                    <= record.trade_date
                    <= min(date.fromisoformat(effective_till), date(2024, 11, 27))
                )
            reconciliation_dates = [record.trade_date for record in reconciliation_history_records]
            if len(reconciliation_dates) != len(set(reconciliation_dates)):
                raise ValueError(
                    f"{ticker}: current and legacy TQBR reconciliation histories overlap"
                )
            reconciliation_history_records.sort(key=lambda record: record.trade_date)
            raw_candles = [
                candle for candle in raw_candles
                if date.fromisoformat(effective_from)
                <= candle.timestamp.date()
                <= date.fromisoformat(effective_till)
            ]
            research_candles, research_eligibility = build_trading_day_candles(
                bounded_history_records, effective_from, effective_till
            )
            initial_session_diagnostics = reconcile_session_candles(
                raw_candles, reconciliation_history_records, ticker=ticker
            )
            comparison_errors = []
            comparison_records = []
            for mismatch_day in initial_session_diagnostics["session_scope_probe_dates"]:
                session_ticker = (
                    "TCSG" if ticker == "T" and mismatch_day <= "2024-11-27"
                    else ticker
                )
                try:
                    morning_history = fetch_history_records(
                        session_ticker, mismatch_day, mismatch_day,
                        board="TQBR", trading_session=0,
                    )
                    main_history = fetch_history_records(
                        session_ticker, mismatch_day, mismatch_day,
                        board="TQBR", trading_session=1,
                    )
                    comparison_records.extend(
                        combine_morning_main_history_records(
                            morning_history, main_history
                        )
                    )
                except Exception as comparison_exc:
                    comparison_errors.append(f"{mismatch_day}: {comparison_exc}")
            comparison_history_records = comparison_records or None
            comparison_history_error = "; ".join(comparison_errors) or None
            session_date_mapping_diagnostics = (
                reconcile_session_candles(
                    raw_candles, reconciliation_history_records, ticker=ticker,
                    comparison_history_records=comparison_history_records,
                )
                if comparison_history_records is not None
                else initial_session_diagnostics
            )
            if not research_candles:
                raise ValueError("No positive-trade TQBR daily OHLCV rows remain")
            try:
                history_crosscheck = audit_tqbr_history(
                    raw_candles, reconciliation_history_records, fetch_from, effective_till
                )
            except Exception as history_exc:
                history_crosscheck = {
                    "status": "HISTORY_CROSSCHECK_UNAVAILABLE",
                    "error": str(history_exc),
                    "exchange_calendar_verified": False,
                }
            # Corporate-action price bases are handled only for model input.
            # Raw candles/history above remain untouched for independent audit.
            research_candles, corporate_action_history_basis = apply_post_event_price_basis(
                ticker, research_candles, minimum_development_bars=200
            )
            if not research_candles:
                raise ValueError(
                    f"{ticker}: no post-corporate-action TQBR candles remain"
                )
            development = [
                candle for candle in research_candles
                if candle.timestamp.date() < date.fromisoformat(HOLDOUT_START_DATE)
            ]
            if corporate_action_history_basis["status"] == "INSUFFICIENT_POST_ACTION_HISTORY":
                results[ticker] = {
                    "status": "INSUFFICIENT_POST_ACTION_HISTORY",
                    "corporate_action_history_basis": corporate_action_history_basis,
                    "research_input_bars": len(research_candles),
                    "development_bars": len(development),
                    "raw_session_candles": len(raw_candles),
                    "raw_reconciliation_history_alias": legacy_alias,
                    "raw_reconciliation_history_alias_error": legacy_history_errors.get(ticker),
                    "raw_comparison_history_error": comparison_history_error,
                    "session_date_mapping": session_date_mapping_diagnostics,
                    "tqbr_history_crosscheck": history_crosscheck,
                }
                continue
            results[ticker] = {
                "status": "ANALYZED",
                "candles": len(research_candles),
                "raw_session_candles": len(raw_candles),
                "first_timestamp": research_candles[0].timestamp.isoformat(),
                "last_timestamp": research_candles[-1].timestamp.isoformat(),
                "data_quality": candle_quality_report(
                    research_candles, effective_from, effective_till,
                    history_records=bounded_history_records,
                    session_date_mapping_complete=True,
                ),
                "raw_candle_fetch_error": raw_candle_fetch_error,
                "raw_candle_quality": candle_quality_report(
                    raw_candles, effective_from, effective_till,
                    history_records=reconciliation_history_records,
                    session_date_mapping_complete=session_date_mapping_diagnostics["complete"],
                ) if raw_candles else None,
                "raw_reconciliation_history_alias": legacy_alias,
                "raw_reconciliation_history_alias_error": legacy_history_errors.get(ticker),
                "raw_comparison_history_error": comparison_history_error,
                "session_date_mapping": session_date_mapping_diagnostics,
                "research_eligibility": research_eligibility,
                "research_input_bars": len(research_candles),
                "corporate_action_history_basis": corporate_action_history_basis,
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
    experiment_lab = {
        "lab_version": "exit-policy-experiments-v1",
        "status": "SKIPPED_NOT_REQUESTED",
        "reason": (
            "Exit-policy experiments are optional and are not part of the "
            "default strategy-selection run. Use --run-experiment-lab to run them."
        ),
        "safety": "Research only; no broker APIs or order placement.",
    }
    if run_experiment_lab_enabled:
        try:
            experiment_lab = run_experiment_lab(
                development_candles_by_ticker,
                holdout_start=HOLDOUT_START_DATE,
                folds=4,
                warmup_bars=200,
                min_total_trades=30,
                min_trades_per_fold=5,
            )
        except Exception as lab_exc:
            experiment_lab = {
                "lab_version": "exit-policy-experiments-v1",
                "status": "EXPERIMENT_LAB_ERROR",
                "error": str(lab_exc),
                "safety": "Research only; no broker APIs or order placement.",
            }

    holdout_correction = apply_holm_correction(results)
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
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "MOEX ISS per-security TQBR daily history OHLCV; raw daily candles retained for reconciliation",
        "board": "TQBR",
        "interval_minutes": 24 * 60,
        "date_from": effective_from,
        "requested_date_from": date_from,
        "history_mapping_fetch_from": fetch_from,
        "history_mapping_fetch_till": history_fetch_till,
        "history_mapping_lookahead_days": 0,
        "date_till": effective_till,
        "requested_date_till": requested_till,
        "daily_bar_completion_policy": {
            "timezone": "Europe/Moscow",
            "maximum_requested_candle_date": calendar_date_ceiling,
            "maximum_completed_session_date": effective_till,
            "current_moscow_date_excluded": True,
            "research_bars_use_tqbr_trade_dates": True,
            "raw_weekend_candles_retained_for_reconciliation": True,
            "weekend_session_launch_date": "2025-03-01",
            "weekend_sessions_included_in_next_trading_day_history_ohlcv": True,
            "official_weekday_additional_sessions": {
                "2026-02-23": "2026-02-24",
                "2026-05-01": "2026-05-04",
                "2026-06-12": "2026-06-15",
                "2026-11-04": "2026-11-05",
            },
            "official_weekday_additional_session_calendar_source": "https://www.moex.com/n96571",
            "reason": (
                "The current Moscow calendar date is excluded. The effective end date is "
                "the latest positive-trade TQBR history date. Research uses one OHLCV "
                "bar per TQBR TRADEDATE; MOEX additional weekend sessions and the "
                "four officially announced 2026 weekday holiday sessions are included "
                "in the next ordinary trading day's daily-history OHLCV. Separate "
                "calendar-date candles are retained only for reconciliation diagnostics."
            ),
        },
        "corporate_action_price_basis_policy": {
            "status": "DIAGNOSTIC_ONLY_NO_AUTOMATIC_ADJUSTMENT",
            "description": (
                "Raw daily candle OHLC is compared with official TQBR history OHLC. "
                "A constant ratio across all four price fields is reported and, where "
                "possible, matched to a sourced corporate-action event. No OHLCV value "
                "is adjusted by this diagnostic."
            ),
            "known_events_reference": "research_agent/corporate_actions.py",
        },
        "session_date_policy": {
            "source": "MOEX ISS public per-security TQBR daily history",
            "research_bar_source": "Per-security TQBR daily history OHLCV, one bar per TRADEDATE",
            "weekend_mapping": (
                "From 2025-03-01, raw Saturday/Sunday candle fragments without a "
                "same-date history row map to the next positive-trade TQBR history "
                "date; MOEX defines the additional weekend session as part of the "
                "next ordinary trading day. Earlier weekend dates require same-date "
                "history confirmation (e.g. a working Saturday)."
            ),
            "aggregation": (
                "The model uses the official TQBR daily-history OHLCV row, which "
                "already aggregates weekend and ordinary sessions. Raw candle "
                "fragments are aggregated only to reconcile against that row."
            ),
            "reconciliation": (
                "Raw calendar-date candles are grouped by TQBR trading date and "
                "their aggregate OHLCV is compared with daily history. Mismatches "
                "and unassigned fragments are reported; history remains the model source."
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
        "legacy_history_fetch_errors": legacy_history_errors,
        "history_alias_policy": {
            "T": {
                "legacy_ticker": "TCSG",
                "legacy_ticker_valid_through": "2024-11-27",
                "current_ticker_effective_from": "2024-11-28",
                "official_source": "https://www.moex.com/n74886",
                "scope": "Raw-candle reconciliation only; TCSG history is not added to research/model input.",
            }
        },
        "results": results,
        "cross_sectional_direction_summary": cross_sectional_direction_summary(results),
        "experiment_lab": experiment_lab,
        "development_portfolio": development_portfolio,
        "safety": "Research only. No broker APIs, order placement, Telegram, or production-state writes.",
    }
    report["independent_validation"] = validate_research_report(report)
    return report

def research_exit_code(report: dict, analyzed: int) -> int:
    """Return non-zero when the saved report fails or cannot complete its audit."""
    validation = report.get("independent_validation", {})
    status = validation.get("status") if isinstance(validation, dict) else None
    if status == "INDEPENDENT_VALIDATION_FAIL":
        return 2
    if status == "INDEPENDENT_VALIDATION_INCOMPLETE":
        return 3
    if status == "INDEPENDENT_VALIDATION_PASS":
        return 0 if analyzed > 0 else 1
    validation_status = status or "MISSING"
    print(f"Independent validation: {validation_status}")
    return 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only MOEX EDGE AI Research Agent")
    parser.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    parser.add_argument("--till", dest="date_till", required=True, help="YYYY-MM-DD")
    parser.add_argument("--tickers", default=",".join(MOEX_FIRST_LISTING_44),
                        help="Comma-separated tickers; defaults to the 44-symbol universe")
    parser.add_argument("--output", default="research_report.json")
    parser.add_argument("--registry-output", default=None)
    parser.add_argument(
        "--run-experiment-lab",
        action="store_true",
        help="Run optional exit-policy experiments (adds substantial research time)",
    )
    args = parser.parse_args()
    tickers = [item.strip().upper() for item in args.tickers.split(",") if item.strip()]
    report = run_universe(args.date_from, args.date_till, tickers, run_experiment_lab_enabled=args.run_experiment_lab)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    registry_path = Path(args.registry_output) if args.registry_output else Path(args.output).with_name("strategy_registry.json")
    registry = build_strategy_registry(report)
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Strategy registry written: " + str(registry_path))
    analyzed = sum(item["status"] == "ANALYZED" for item in report["results"].values())
    errors = len(report["results"]) - analyzed
    print(f"Research complete: {analyzed} analyzed, {errors} errors; report={args.output}")
    return research_exit_code(report, analyzed)


if __name__ == "__main__":
    raise SystemExit(main())