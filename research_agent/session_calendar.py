"""MOEX stock-market calendar and daily-session aggregation.

Weekend additional sessions are mapped to the official next trading-session
date before any indicator or backtest is calculated.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from urllib.parse import urlencode

from .core import Candle, validate_candles
from .moex_iss import ISS_BASE, _get_json


class SessionCalendarError(ValueError):
    """Raised when exchange calendar data is missing or inconsistent."""


@dataclass(frozen=True)
class StockCalendarRecord:
    trade_date: date
    is_traded: int | None
    trade_session_date: date | None
    reason: str | None


def fetch_stock_calendar(
    date_from: str,
    date_till: str,
    timeout: int = 20,
    retries: int = 3,
    getter=_get_json,
) -> dict[date, StockCalendarRecord]:
    """Fetch the complete MOEX stock calendar, split into calendar-year requests."""
    start_date = date.fromisoformat(date_from)
    end_date = date.fromisoformat(date_till)
    if start_date > end_date:
        raise ValueError("date_from must be on or before date_till")

    result: dict[date, StockCalendarRecord] = {}
    for year in range(start_date.year, end_date.year + 1):
        chunk_start = max(start_date, date(year, 1, 1))
        chunk_end = min(end_date, date(year, 12, 31))
        offset = 0
        while True:
            query = urlencode({
                "from": chunk_start.isoformat(),
                "till": chunk_end.isoformat(),
                "show_all_days": "1",
                "iss.only": "off_days",
                "iss.meta": "off",
                "start": offset,
            })
            payload = getter(
                f"{ISS_BASE}/calendars/stock.json?{query}",
                timeout=timeout,
                retries=retries,
            )
            block = payload.get("off_days")
            if (not isinstance(block, dict)
                    or not isinstance(block.get("columns"), list)
                    or not isinstance(block.get("data"), list)):
                raise SessionCalendarError("MOEX ISS response lacks a valid stock-calendar off_days block")
            columns = block["columns"]
            required = {"tradedate", "is_traded", "trade_session_date", "reason"}
            if not required.issubset(columns):
                raise SessionCalendarError(
                    f"MOEX stock-calendar columns missing: {sorted(required - set(columns))}"
                )
            idx = {name: columns.index(name) for name in required}
            rows = block["data"]
            for row in rows:
                try:
                    tradeday = date.fromisoformat(str(row[idx["tradedate"]]))
                    raw_is_traded = row[idx["is_traded"]]
                    is_traded = None if raw_is_traded is None else int(raw_is_traded)
                    if is_traded not in (None, 0, 1):
                        raise ValueError("is_traded must be 0, 1, or null")
                    raw_session_date = row[idx["trade_session_date"]]
                    session_date = (
                        None if raw_session_date in (None, "")
                        else date.fromisoformat(str(raw_session_date))
                    )
                    raw_reason = row[idx["reason"]]
                    reason = None if raw_reason in (None, "") else str(raw_reason).upper()
                    if tradeday < chunk_start or tradeday > chunk_end:
                        raise ValueError(f"Calendar date outside requested chunk: {tradeday}")
                except (IndexError, TypeError, ValueError) as exc:
                    raise SessionCalendarError(f"Malformed MOEX stock-calendar row: {exc}") from exc
                if tradeday in result:
                    raise SessionCalendarError(f"Duplicate MOEX stock-calendar date: {tradeday}")
                result[tradeday] = StockCalendarRecord(
                    tradeday, is_traded, session_date, reason
                )
            if not rows:
                break
            offset += len(rows)

        expected_days = (chunk_end - chunk_start).days + 1
        actual_days = sum(chunk_start <= day <= chunk_end for day in result)
        if actual_days != expected_days:
            raise SessionCalendarError(
                f"Incomplete MOEX stock calendar for {year}: "
                f"expected {expected_days} dates, received {actual_days}"
            )

    return result


def session_date_for_calendar_record(record: StockCalendarRecord) -> date:
    """Resolve a calendar date to the MOEX trading-session date."""
    if record.is_traded != 1:
        raise SessionCalendarError(
            f"Candle exists on a non-trading/unknown stock-calendar date: {record.trade_date}"
        )
    if record.reason == "W":
        if record.trade_session_date is None:
            raise SessionCalendarError(
                f"Weekend session has no trade_session_date: {record.trade_date}"
            )
        if record.trade_session_date <= record.trade_date:
            raise SessionCalendarError(
                f"Invalid weekend session mapping: {record.trade_date} -> {record.trade_session_date}"
            )
        return record.trade_session_date
    if record.reason in ("N", "T"):
        if record.trade_session_date not in (None, record.trade_date):
            raise SessionCalendarError(
                f"Unexpected session mapping for {record.reason} date {record.trade_date}"
            )
        return record.trade_date
    raise SessionCalendarError(
        f"Unsupported trading-calendar reason {record.reason!r} on {record.trade_date}"
    )


def _resolve_session_date(
    record: StockCalendarRecord,
    calendar: dict[date, StockCalendarRecord],
) -> date:
    session_day = session_date_for_calendar_record(record)
    if session_day != record.trade_date:
        target = calendar.get(session_day)
        if target is None or target.is_traded != 1 or target.reason not in ("N", "T"):
            raise SessionCalendarError(
                f"Weekend session target is not a verified trading date: "
                f"{record.trade_date} -> {session_day}"
            )
    return session_day


def earliest_session_date(
    calendar: dict[date, StockCalendarRecord],
    calendar_date_floor: str | date,
) -> date:
    """Return the first official session represented on/after the requested date."""
    floor = (
        date.fromisoformat(calendar_date_floor)
        if isinstance(calendar_date_floor, str)
        else calendar_date_floor
    )
    candidates = []
    for tradeday, record in calendar.items():
        if tradeday < floor or record.is_traded != 1:
            continue
        session_day = _resolve_session_date(record, calendar)
        if session_day >= floor:
            candidates.append(session_day)
    if not candidates:
        raise SessionCalendarError(
            f"No MOEX stock session exists on or after {floor}"
        )
    return min(candidates)


def latest_completed_session_date(
    calendar: dict[date, StockCalendarRecord],
    calendar_date_ceiling: str | date,
) -> date:
    """Return the latest session whose entire calendar session date has completed."""
    ceiling = (
        date.fromisoformat(calendar_date_ceiling)
        if isinstance(calendar_date_ceiling, str)
        else calendar_date_ceiling
    )
    completed = []
    for tradeday, record in calendar.items():
        if tradeday > ceiling or record.is_traded != 1:
            continue
        session_day = _resolve_session_date(record, calendar)
        if session_day <= ceiling:
            completed.append(session_day)
    if not completed:
        raise SessionCalendarError(
            f"No completed MOEX stock session exists on or before {ceiling}"
        )
    return max(completed)


def normalize_daily_candles(
    candles: list[Candle],
    calendar: dict[date, StockCalendarRecord],
    max_session_date: str | date | None = None,
) -> tuple[list[Candle], dict]:
    """Aggregate additional weekend candles into their official MOEX session day."""
    rows = validate_candles(candles)
    ceiling = None
    if isinstance(max_session_date, str):
        ceiling = date.fromisoformat(max_session_date)
    elif max_session_date is not None:
        ceiling = max_session_date

    grouped: dict[date, list[Candle]] = defaultdict(list)
    mapped_weekend_dates = []
    for candle in rows:
        source_date = candle.timestamp.date()
        record = calendar.get(source_date)
        if record is None:
            raise SessionCalendarError(
                f"Missing MOEX stock-calendar row for candle date {source_date}"
            )
        session_day = _resolve_session_date(record, calendar)
        if record.reason == "W":
            mapped_weekend_dates.append({
                "calendar_date": source_date.isoformat(),
                "trade_session_date": session_day.isoformat(),
            })
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
        "calendar_source": "MOEX ISS stock calendar /iss/calendars/stock.json",
        "aggregation_rule": (
            "Calendar reason W maps to trade_session_date; OHLCV is combined "
            "chronologically into one trading-session candle."
        ),
        "raw_candles": len(rows),
        "normalized_session_candles": len(normalized),
        "weekend_session_candles_mapped": len(mapped_weekend_dates),
        "weekend_session_mappings": mapped_weekend_dates,
        "sessions_combining_multiple_calendar_dates": combined_sessions,
        "source_bars_excluded_beyond_completed_session_cutoff": excluded_source_bars,
        "exchange_calendar_verified": True,
    }
    return normalized, diagnostics
