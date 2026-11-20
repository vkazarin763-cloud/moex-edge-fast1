"""Conservative handling of MOEX daily candles and weekend-session evidence.

Weekend candles remain on their original calendar dates. Public per-security
TQBR history can confirm a same-date positive-trade session, but absence of a
history row never causes a candle to be shifted or merged into another date.
The subscription-only machine-readable MOEX calendar is not available here.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time

from .core import Candle, validate_candles
from .moex_iss import HistoryRecord


class SessionMappingError(ValueError):
    """Raised when history-backed session mapping is inconsistent."""


def _records_by_date(records: list[HistoryRecord]) -> dict[date, HistoryRecord]:
    result = {}
    for record in records:
        if record.trade_date in result:
            raise SessionMappingError(f"Duplicate TQBR history date: {record.trade_date}")
        result[record.trade_date] = record
    return result


def latest_completed_session_date(
    records_by_ticker: dict[str, list[HistoryRecord] | None],
    calendar_date_ceiling: str | date,
) -> date:
    """Latest positive-trade TQBR date across the selected universe up to cutoff."""
    ceiling = (
        date.fromisoformat(calendar_date_ceiling)
        if isinstance(calendar_date_ceiling, str)
        else calendar_date_ceiling
    )
    candidates = [
        record.trade_date
        for records in records_by_ticker.values()
        if records
        for record in records
        if record.trade_date <= ceiling
        and record.num_trades is not None
        and record.num_trades > 0
    ]
    if not candidates:
        raise SessionMappingError(
            f"No positive-trade TQBR history date exists on or before {ceiling}"
        )
    return max(candidates)


def earliest_session_date(
    records_by_ticker: dict[str, list[HistoryRecord] | None],
    date_floor: str | date,
    date_ceiling: str | date,
) -> date:
    """Earliest positive-trade TQBR date in the effective requested range."""
    floor = date.fromisoformat(date_floor) if isinstance(date_floor, str) else date_floor
    ceiling = date.fromisoformat(date_ceiling) if isinstance(date_ceiling, str) else date_ceiling
    candidates = [
        record.trade_date
        for records in records_by_ticker.values()
        if records
        for record in records
        if floor <= record.trade_date <= ceiling
        and record.num_trades is not None
        and record.num_trades > 0
    ]
    if not candidates:
        raise SessionMappingError(
            f"No positive-trade TQBR history date exists between {floor} and {ceiling}"
        )
    return min(candidates)


def research_eligible_candles(
    candles: list[Candle],
    history_records: list[HistoryRecord],
) -> tuple[list[Candle], dict]:
    """Exclude unverified weekend bars from indicators and simulations.

    Raw bars remain available for diagnostics. Weekday bars are retained as
    supplied; weekend bars enter research calculations only when same-date
    TQBR history confirms positive NUMTRADES.
    """
    rows = validate_candles(candles)
    by_date = _records_by_date(history_records)
    eligible = []
    excluded = []
    for candle in rows:
        day = candle.timestamp.date()
        if day.weekday() < 5:
            eligible.append(candle)
            continue
        record = by_date.get(day)
        if record is not None and record.num_trades is not None and record.num_trades > 0:
            eligible.append(candle)
        else:
            excluded.append({
                "calendar_date": day.isoformat(),
                "volume": candle.volume,
                "reason": "weekend session not confirmed by same-date positive TQBR NUMTRADES",
            })
    if eligible:
        eligible = validate_candles(eligible)
    return eligible, {
        "raw_bars": len(rows),
        "research_eligible_bars": len(eligible),
        "unverified_weekend_bars_excluded_from_models": len(excluded),
        "excluded_weekend_bars": excluded,
        "policy": (
            "Unverified weekend candles remain in raw diagnostics but are excluded "
            "from indicator calculation, walk-forward, cost stress, portfolio replay, "
            "and prospective holdout. Same-date positive TQBR NUMTRADES is required "
            "to include a weekend candle in research calculations."
        ),
    }


def normalize_daily_candles(
    candles: list[Candle],
    history_records: list[HistoryRecord],
    max_session_date: str | date | None = None,
) -> tuple[list[Candle], dict]:
    """Preserve each MOEX candle date unless TQBR confirms that same date.

    TQBR history often has no row for weekend sessions. Absence of a history row
    is not evidence that the weekend candle belongs to the following weekday.
    Therefore this function never shifts or merges a weekend candle into a
    future date. Unconfirmed weekend dates remain separate and are flagged.
    """
    rows = validate_candles(candles)
    ceiling = None
    if isinstance(max_session_date, str):
        ceiling = date.fromisoformat(max_session_date)
    elif max_session_date is not None:
        ceiling = max_session_date

    by_date = _records_by_date(history_records)
    normalized = []
    weekend_diagnostics = []
    excluded_after_cutoff = 0
    for candle in rows:
        source_date = candle.timestamp.date()
        if ceiling is not None and source_date > ceiling:
            excluded_after_cutoff += 1
            continue
        if source_date.weekday() >= 5:
            record = by_date.get(source_date)
            confirmed = (
                record is not None
                and record.num_trades is not None
                and record.num_trades > 0
            )
            weekend_diagnostics.append({
                "calendar_date": source_date.isoformat(),
                "trade_session_date": source_date.isoformat(),
                "mapping_basis": (
                    "same-date positive NUMTRADES"
                    if confirmed
                    else "preserved as its own calendar date; TQBR session unverified"
                ),
                "verified_by_tqbr_history": confirmed,
                "volume": candle.volume,
            })
        normalized.append(candle)

    normalized = validate_candles(normalized) if normalized else []
    unverified = [
        item for item in weekend_diagnostics
        if not item["verified_by_tqbr_history"]
    ]
    diagnostics = {
        "mapping_source": "MOEX ISS daily candles; optional same-date TQBR history cross-check",
        "mapping_rule": (
            "Weekend candles remain on their original calendar dates. No forward "
            "mapping or aggregation is performed without an authoritative session calendar."
        ),
        "mapping_is_inferred_not_direct_calendar_lookup": True,
        "raw_candles": len(rows),
        "normalized_session_candles": len(normalized),
        "weekend_candles_preserved": len(weekend_diagnostics),
        "weekend_session_mappings": weekend_diagnostics,
        "unresolved_weekend_candles": unverified,
        "weekday_candles_without_history_record": [
            candle.timestamp.date().isoformat()
            for candle in normalized
            if candle.timestamp.weekday() < 5
            and candle.timestamp.date() not in by_date
        ],
        "sessions_combining_multiple_calendar_dates": [],
        "source_bars_excluded_beyond_completed_session_cutoff": excluded_after_cutoff,
        "session_date_mapping_complete": not unverified,
        "warning": (
            "Weekend candles are retained as separate bars but their official "
            "trading-session classification is unverified."
            if unverified else None
        ),
    }
    return normalized, diagnostics
