"""Descriptive candle-quality audits for the read-only MOEX research pipeline."""
from __future__ import annotations

from datetime import date
from typing import Any

from .core import Candle, validate_candles
from .moex_iss import HistoryRecord


def candle_quality_report(
    candles: list[Candle],
    requested_from: str | None = None,
    requested_till: str | None = None,
    warmup_bars: int = 200,
    preferred_min_bars: int = 500,
    history_records: list[HistoryRecord] | None = None,
    session_date_mapping_complete: bool = False,
) -> dict[str, Any]:
    """Return validated-series diagnostics without assuming an exchange calendar."""
    if warmup_bars < 0 or preferred_min_bars < warmup_bars:
        raise ValueError("preferred_min_bars must be >= warmup_bars >= 0")

    rows = validate_candles(candles)
    first = rows[0].timestamp.date()
    last = rows[-1].timestamp.date()

    gaps = []
    for previous, current in zip(rows, rows[1:]):
        delta = (current.timestamp.date() - previous.timestamp.date()).days
        if delta > 3:
            weekdays = sum(
                date.fromordinal(ordinal).weekday() < 5
                for ordinal in range(previous.timestamp.date().toordinal() + 1,
                                     current.timestamp.date().toordinal())
            )
            gaps.append({
                "from": previous.timestamp.date().isoformat(),
                "to": current.timestamp.date().isoformat(),
                "calendar_days_between": delta - 1,
                "weekdays_between_unverified": weekdays,
                "classification": "UNVERIFIED_CALENDAR_GAP",
            })

    requested_start = date.fromisoformat(requested_from) if requested_from else None
    requested_end = date.fromisoformat(requested_till) if requested_till else None
    if requested_start and requested_end and requested_start > requested_end:
        raise ValueError("requested_from must be on or before requested_till")

    start_delay = (first - requested_start).days if requested_start else None
    end_lag = (requested_end - last).days if requested_end else None
    starts_before_range = bool(requested_start and first < requested_start)
    ends_after_range = bool(requested_end and last > requested_end)
    out_of_range_bars = sum(
        bool((requested_start and row.timestamp.date() < requested_start)
             or (requested_end and row.timestamp.date() > requested_end))
        for row in rows
    )
    boundary_missing = bool(
        (start_delay is not None and start_delay > 0)
        or (end_lag is not None and end_lag > 0)
    )
    outside_requested_range = starts_before_range or ends_after_range

    if len(rows) < warmup_bars:
        history_status = "BELOW_WARMUP"
    elif len(rows) < preferred_min_bars:
        history_status = "WARMUP_ONLY_SHORT_HISTORY"
    else:
        history_status = "PREFERRED_HISTORY_LENGTH"

    zero_volume = sum(c.volume == 0 for c in rows)
    weekend_rows = [c for c in rows if c.timestamp.weekday() >= 5]
    weekend = len(weekend_rows)
    history_by_date = {}
    if history_records is not None:
        for record in history_records:
            if record.trade_date in history_by_date:
                raise ValueError(f"Duplicate TQBR history date: {record.trade_date}")
            history_by_date[record.trade_date] = record.num_trades
    verified_weekend = sum(
        history_by_date.get(c.timestamp.date()) is not None
        and history_by_date[c.timestamp.date()] > 0
        for c in weekend_rows
    )
    weekend_zero_trade = sum(
        c.timestamp.date() in history_by_date
        and history_by_date[c.timestamp.date()] == 0
        for c in weekend_rows
    )
    weekend_unknown_history = sum(
        c.timestamp.date() in history_by_date
        and history_by_date[c.timestamp.date()] is None
        for c in weekend_rows
    )
    weekend_without_history = weekend - verified_weekend - weekend_zero_trade - weekend_unknown_history
    unverified_weekend = weekend - verified_weekend
    has_caveats = (
        gaps or zero_volume or unverified_weekend
        or history_status != "PREFERRED_HISTORY_LENGTH"
        or boundary_missing or outside_requested_range
        or not session_date_mapping_complete
    )
    if outside_requested_range:
        range_boundary_status = "OUTSIDE_REQUESTED_RANGE"
    elif boundary_missing:
        range_boundary_status = "BOUNDARY_REQUIRES_REVIEW"
    else:
        range_boundary_status = "REQUESTED_RANGE_COVERED"

    return {
        "status": "VALID_WITH_CAVEATS" if has_caveats else "VALID",
        "range_boundary_status": range_boundary_status,
        "bars": len(rows),
        "first_timestamp": rows[0].timestamp.isoformat(),
        "last_timestamp": rows[-1].timestamp.isoformat(),
        "requested_from": requested_from,
        "requested_till": requested_till,
        "start_delay_calendar_days": start_delay,
        "end_lag_calendar_days": end_lag,
        "starts_before_requested_range": starts_before_range,
        "ends_after_requested_range": ends_after_range,
        "out_of_range_bars": out_of_range_bars,
        "checks": {
            "strictly_increasing_timestamps": "PASS",
            "duplicate_timestamps": "PASS (loader rejects duplicates before analysis)",
            "finite_positive_ohlc": "PASS",
            "ohlc_relationships": "PASS",
            "non_negative_volume": "PASS",
        },
        "zero_volume_bars": zero_volume,
        "weekend_bars": weekend,
        "weekend_session_diagnostics": {
            "verified_trade_bars": verified_weekend,
            "unverified_bars": unverified_weekend,
            "candles_on_zero_trade_dates": weekend_zero_trade,
            "history_rows_with_unknown_trade_count": weekend_unknown_history,
            "dates_without_history_rows": weekend_without_history,
            "verification_source": (
                "Same-date TQBR history match only; weekend session fragments may "
                "be included in the next ordinary trading day's history OHLCV and "
                "are checked by the session reconciliation diagnostic."
                if history_records is not None
                else "Unavailable; see TQBR trading-day history reconciliation"
            ),
        },
        "calendar_gap_candidates": gaps,
        "calendar_gap_count": len(gaps),
        "exchange_calendar_verified": False,
        "session_date_mapping_complete": session_date_mapping_complete,
        "calendar_caveat": (
            "Raw weekend candles are calendar-session fragments. Research D1 input "
            "uses per-security TQBR daily-history TRADEDATE OHLCV, which includes "
            "the additional weekend session in the next ordinary trading day's bar. "
            "Raw fragments are reconciled against history; this is not a direct "
            "historical exchange-calendar lookup."
        ),
        "history_status": history_status,
        "warmup_bars_required": warmup_bars,
        "preferred_min_bars": preferred_min_bars,
    }


def audit_tqbr_history(
    candles: list[Candle],
    history_records: list[HistoryRecord],
    requested_from: str,
    requested_till: str,
    session_mapping_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cross-check candle dates only against explicit per-security TQBR rows."""
    start = date.fromisoformat(requested_from)
    end = date.fromisoformat(requested_till)
    if start > end:
        raise ValueError("requested_from must be on or before requested_till")
    candle_dates = {row.timestamp.date() for row in validate_candles(candles)}
    out_of_range_candles = sorted(
        day.isoformat() for day in candle_dates if day < start or day > end
    )
    if out_of_range_candles:
        raise ValueError(f"Candle dates outside requested range: {out_of_range_candles}")
    records_by_date: dict[date, HistoryRecord] = {}
    for record in history_records:
        if record.trade_date < start or record.trade_date > end:
            raise ValueError(f"TQBR history date outside requested range: {record.trade_date}")
        if record.trade_date in records_by_date:
            raise ValueError(f"Duplicate TQBR history date: {record.trade_date}")
        records_by_date[record.trade_date] = record

    missing_on_trade_dates = []
    zero_trade_without_candle = []
    candle_with_zero_trades = []
    unknown_trade_count = []
    for trade_date, record in sorted(records_by_date.items()):
        has_candle = trade_date in candle_dates
        if record.num_trades is None:
            unknown_trade_count.append(trade_date.isoformat())
        elif record.num_trades > 0 and not has_candle:
            missing_on_trade_dates.append({
                "date": trade_date.isoformat(),
                "num_trades": record.num_trades,
            })
        elif record.num_trades == 0 and not has_candle:
            zero_trade_without_candle.append(trade_date.isoformat())
        elif record.num_trades == 0 and has_candle:
            candle_with_zero_trades.append(trade_date.isoformat())

    weekend_dates_without_same_date_history = {
        row.timestamp.date() for row in validate_candles(candles)
        if row.timestamp.weekday() >= 5 and row.timestamp.date() not in records_by_date
    }
    weekend_mapping_verified = bool(
        isinstance(session_mapping_diagnostics, dict)
        and isinstance(session_mapping_diagnostics.get("raw_weekend_candles"), int)
        and session_mapping_diagnostics.get("raw_weekend_candles_mapped")
            == session_mapping_diagnostics.get("raw_weekend_candles")
        and session_mapping_diagnostics.get("raw_weekend_candles_unmapped") == 0
    )
    weekday_additional_mapping_verified = bool(
        isinstance(session_mapping_diagnostics, dict)
        and isinstance(session_mapping_diagnostics.get("raw_weekday_additional_session_candles"), int)
        and session_mapping_diagnostics.get("raw_weekday_additional_session_candles_mapped")
            == session_mapping_diagnostics.get("raw_weekday_additional_session_candles")
        and session_mapping_diagnostics.get("raw_weekday_additional_session_candles_unmapped") == 0
    )
    weekday_additional_dates_without_same_date_history = set()
    if weekday_additional_mapping_verified:
        raw_additional_dates = session_mapping_diagnostics.get("weekday_additional_session_dates", [])
        if isinstance(raw_additional_dates, list):
            for raw_date in raw_additional_dates:
                if isinstance(raw_date, str):
                    try:
                        parsed_date = date.fromisoformat(raw_date)
                    except ValueError:
                        continue
                    if parsed_date not in records_by_date:
                        weekday_additional_dates_without_same_date_history.add(parsed_date)
    expected_mapped_weekend_dates = (
        weekend_dates_without_same_date_history if weekend_mapping_verified else set()
    )
    expected_mapped_session_dates = (
        expected_mapped_weekend_dates | weekday_additional_dates_without_same_date_history
    )
    candles_without_history = sorted(
        trade_date.isoformat() for trade_date in candle_dates
        if trade_date not in records_by_date
        and trade_date not in expected_mapped_session_dates
    )
    if not records_by_date:
        status = "NO_HISTORY_RECORDS"
    elif missing_on_trade_dates:
        status = "MISSING_CANDLE_ON_RECORDED_TRADE_DATE"
    elif unknown_trade_count or candle_with_zero_trades or candles_without_history:
        status = "CROSSCHECK_INCONCLUSIVE"
    else:
        status = "NO_MISSING_CANDLE_DETECTED_ON_RECORDED_TRADE_DATES"

    return {
        "status": status,
        "source": "MOEX ISS public TQBR per-security daily history",
        "history_rows": len(records_by_date),
        "history_rows_with_trades": sum(
            record.num_trades is not None and record.num_trades > 0
            for record in records_by_date.values()
        ),
        "missing_candles_on_trade_dates": missing_on_trade_dates,
        "zero_trade_sessions_without_candles": zero_trade_without_candle,
        "candles_present_on_zero_trade_dates": candle_with_zero_trades,
        "history_rows_unknown_trade_count": unknown_trade_count,
        "candles_without_history_record": candles_without_history,
        "mapped_weekend_fragments_without_same_date_history": len(expected_mapped_weekend_dates),
        "weekend_fragments_excluded_from_same_date_crosscheck": weekend_mapping_verified,
        "mapped_weekday_additional_session_fragments_without_same_date_history": len(
            weekday_additional_dates_without_same_date_history
        ),
        "weekday_additional_session_fragments_excluded_from_same_date_crosscheck": weekday_additional_mapping_verified,
        "coverage_scope": (
            "Only dates explicitly returned for this security on TQBR are checked. "
            "Weekend and official weekday additional-session calendar-date fragments are "
            "excluded from same-date mismatch classification only when the independent "
            "session mapper confirms every such fragment is mapped to a positive-trade "
            "TQBR date with zero unmapped fragments. This does not independently verify "
            "the exchange-wide calendar. No row is not proof of a holiday, suspension, "
            "or listing boundary."
        ),
        "exchange_calendar_verified": False,
    }
