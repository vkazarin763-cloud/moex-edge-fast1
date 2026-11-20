"""History-backed MOEX daily session mapping.

The public per-security TQBR history is used to infer the trading-session date
for weekend candles. This deliberately does not claim direct calendar access:
the machine-readable MOEX calendar endpoint requires a subscription.
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


def normalize_daily_candles(
    candles: list[Candle],
    history_records: list[HistoryRecord],
    max_session_date: str | date | None = None,
) -> tuple[list[Candle], dict]:
    """Map weekend candles to the next positive TQBR history date and aggregate OHLCV.

    A positive same-date TQBR history row identifies a transferred weekend workday
    and keeps that date. Otherwise a weekend candle with positive volume is mapped
    to the next later positive-trade history date for that same security. If no
    target date can be established, the weekend candle is excluded and reported.
    """
    rows = validate_candles(candles)
    ceiling = None
    if isinstance(max_session_date, str):
        ceiling = date.fromisoformat(max_session_date)
    elif max_session_date is not None:
        ceiling = max_session_date

    by_date = _records_by_date(history_records)
    future_trade_dates = sorted(
        record.trade_date
        for record in history_records
        if record.num_trades is not None and record.num_trades > 0
    )

    grouped: dict[date, list[Candle]] = defaultdict(list)
    weekend_mappings = []
    unresolved_weekend = []
    weekday_candles_without_history = []

    for candle in rows:
        source_date = candle.timestamp.date()
        record = by_date.get(source_date)
        if source_date.weekday() >= 5:
            if record is not None:
                if record.num_trades is not None and record.num_trades > 0:
                    session_day = source_date
                else:
                    unresolved_weekend.append({
                        "calendar_date": source_date.isoformat(),
                        "reason": "same-date TQBR history does not confirm positive trades",
                    })
                    continue
            else:
                if candle.volume <= 0:
                    unresolved_weekend.append({
                        "calendar_date": source_date.isoformat(),
                        "reason": "zero-volume weekend candle has no same-date trade record",
                    })
                    continue
                target_dates = [day for day in future_trade_dates if day > source_date]
                if not target_dates:
                    unresolved_weekend.append({
                        "calendar_date": source_date.isoformat(),
                        "reason": "no later positive-trade TQBR history date is available yet",
                    })
                    continue
                session_day = target_dates[0]
            weekend_mappings.append({
                "calendar_date": source_date.isoformat(),
                "trade_session_date": session_day.isoformat(),
                "mapping_basis": (
                    "same-date positive NUMTRADES"
                    if session_day == source_date
                    else "next later positive NUMTRADES date"
                ),
            })
        else:
            session_day = source_date
            if record is None:
                weekday_candles_without_history.append(source_date.isoformat())

        grouped[session_day].append(candle)

    normalized = []
    excluded_source_bars = 0
    combined_sessions = []
    for session_day in sorted(grouped):
        session_bars = sorted(grouped[session_day], key=lambda item: item.timestamp)
        if ceiling is not None and session_day > ceiling:
            excluded_source_bars += len(session_bars)
            continue
        tzinfo = session_bars[0].timestamp.tzinfo
        timestamp = datetime.combine(session_day, time.min, tzinfo=tzinfo)
        normalized.append(Candle(
            timestamp=timestamp,
            open=session_bars[0].open,
            high=max(item.high for item in session_bars),
            low=min(item.low for item in session_bars),
            close=session_bars[-1].close,
            volume=sum(item.volume for item in session_bars),
        ))
        if len(session_bars) > 1:
            combined_sessions.append({
                "trade_session_date": session_day.isoformat(),
                "source_calendar_dates": [
                    item.timestamp.date().isoformat() for item in session_bars
                ],
                "source_bar_count": len(session_bars),
            })

    normalized = validate_candles(normalized) if normalized else []
    diagnostics = {
        "mapping_source": "MOEX ISS public per-security TQBR daily history",
        "mapping_rule": (
            "Positive same-date NUMTRADES keeps a transferred weekend workday; "
            "otherwise a positive-volume weekend candle maps to the next later "
            "positive NUMTRADES date for that security."
        ),
        "mapping_is_inferred_not_direct_calendar_lookup": True,
        "raw_candles": len(rows),
        "normalized_session_candles": len(normalized),
        "weekend_candles_mapped": len(weekend_mappings),
        "weekend_session_mappings": weekend_mappings,
        "unresolved_weekend_candles": unresolved_weekend,
        "weekday_candles_without_history_record": weekday_candles_without_history,
        "sessions_combining_multiple_calendar_dates": combined_sessions,
        "source_bars_excluded_beyond_completed_session_cutoff": excluded_source_bars,
        "session_date_mapping_verified": not unresolved_weekend,
    }
    return normalized, diagnostics
