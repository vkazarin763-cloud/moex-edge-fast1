"""Conservative handling of MOEX daily candles and weekend-session evidence.

Weekend candles remain on their original calendar dates. Public per-security
TQBR history can confirm a same-date positive-trade session, but absence of a
history row never causes a candle to be shifted or merged into another date.
The subscription-only machine-readable MOEX calendar is not available here.
"""
from __future__ import annotations

from collections import defaultdict
import math
from datetime import date, datetime, time, timedelta

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



def build_trading_day_candles(
    history_records: list[HistoryRecord],
    date_from: str | date | None = None,
    date_till: str | date | None = None,
) -> tuple[list[Candle], dict]:
    """Build one D1 bar per official TQBR trading date from daily history.

    TQBR daily history contains the full trading-day OHLCV. MOEX weekend
    additional sessions are part of the next ordinary trading day, so their
    Saturday/Sunday candle fragments are already included in that next date's
    history OHLCV. These fragments must not be treated as extra D1 bars.
    """
    start = date.fromisoformat(date_from) if isinstance(date_from, str) else date_from
    end = date.fromisoformat(date_till) if isinstance(date_till, str) else date_till
    by_date = _records_by_date(history_records)
    if start is not None and end is not None and start > end:
        raise SessionMappingError("date_from must be on or before date_till")

    candles = []
    zero_trade_rows = 0
    unknown_trade_rows = 0
    missing_ohlcv_rows = []
    for record in sorted(by_date.values(), key=lambda item: item.trade_date):
        if start is not None and record.trade_date < start:
            continue
        if end is not None and record.trade_date > end:
            continue
        if record.num_trades is None:
            unknown_trade_rows += 1
            continue
        if record.num_trades == 0:
            zero_trade_rows += 1
            continue
        values = (record.open, record.high, record.low, record.close, record.volume)
        if any(value is None for value in values):
            missing_ohlcv_rows.append(record.trade_date.isoformat())
            continue
        candles.append(Candle(
            datetime.combine(record.trade_date, time.min),
            float(record.open), float(record.high), float(record.low),
            float(record.close), float(record.volume),
        ))
    if missing_ohlcv_rows:
        raise SessionMappingError(
            "Positive-trade TQBR history rows lack complete OHLCV: "
            + ", ".join(missing_ohlcv_rows[:10])
        )
    if not candles:
        raise SessionMappingError("No positive-trade TQBR OHLCV rows remain in the requested range")
    candles = validate_candles(candles)
    return candles, {
        "source": "MOEX ISS per-security TQBR daily history",
        "bar_semantics": (
            "One OHLCV bar per TQBR trading date. Saturday/Sunday additional "
            "sessions are included in the next ordinary trading day's history row."
        ),
        "research_input_bars": len(candles),
        "zero_trade_history_rows_excluded": zero_trade_rows,
        "unknown_trade_count_rows_excluded": unknown_trade_rows,
        "positive_trade_rows_missing_ohlcv": 0,
        "first_trade_date": candles[0].timestamp.date().isoformat(),
        "last_trade_date": candles[-1].timestamp.date().isoformat(),
    }


def reconcile_session_candles(
    raw_candles: list[Candle],
    history_records: list[HistoryRecord],
    max_next_trading_day_gap: int = 3,
) -> dict:
    """Check calendar-date candle fragments against full TQBR trading-day OHLCV.

    A weekend candle without a same-date history row is assigned to the next
    positive-trade TQBR history date within the bounded calendar gap. All
    fragments assigned to a trade date (weekend plus that date's weekday
    candle) are aggregated and compared with the official history OHLCV.
    History remains the model-input source even when this diagnostic finds a
    mismatch; mismatches are surfaced rather than silently repaired.
    """
    if max_next_trading_day_gap < 1:
        raise ValueError("max_next_trading_day_gap must be >= 1")
    rows = validate_candles(raw_candles) if raw_candles else []
    by_date = _records_by_date(history_records)
    positive_dates = sorted(
        record.trade_date for record in history_records
        if record.num_trades is not None and record.num_trades > 0
    )
    grouped = defaultdict(list)
    unassigned = []
    for candle in rows:
        day = candle.timestamp.date()
        same_date = by_date.get(day)
        if same_date is not None:
            if same_date.num_trades is not None and same_date.num_trades > 0:
                target = day
            else:
                unassigned.append({
                    "calendar_date": day.isoformat(),
                    "reason": "same-date TQBR history does not confirm positive trades",
                })
                continue
        elif day.weekday() >= 5:
            target = next((
                candidate for candidate in positive_dates
                if day < candidate
                and (candidate - day).days <= max_next_trading_day_gap
            ), None)
            if target is None:
                unassigned.append({
                    "calendar_date": day.isoformat(),
                    "reason": "no next positive-trade TQBR date within mapping window",
                })
                continue
        else:
            unassigned.append({
                "calendar_date": day.isoformat(),
                "reason": "weekday candle has no same-date TQBR history row",
            })
            continue
        grouped[target].append(candle)

    matched = []
    mismatches = []
    for target, fragments in sorted(grouped.items()):
        record = by_date[target]
        expected = (record.open, record.high, record.low, record.close, record.volume)
        if any(value is None for value in expected):
            mismatches.append({
                "trade_date": target.isoformat(),
                "reason": "TQBR history row lacks complete OHLCV",
                "fragment_count": len(fragments),
            })
            continue
        fragments.sort(key=lambda item: item.timestamp)
        actual = (
            fragments[0].open,
            max(item.high for item in fragments),
            min(item.low for item in fragments),
            fragments[-1].close,
            sum(item.volume for item in fragments),
        )
        fields = ("open", "high", "low", "close", "volume")
        differences = {}
        for name, got, want in zip(fields, actual, expected):
            tolerance = max(1e-8, abs(float(want)) * 1e-8)
            if not math.isclose(float(got), float(want), rel_tol=0.0, abs_tol=tolerance):
                differences[name] = {"aggregated": got, "history": want}
        if differences:
            mismatches.append({
                "trade_date": target.isoformat(),
                "reason": "aggregated calendar candles differ from TQBR daily history",
                "fragment_count": len(fragments),
                "differences": differences,
            })
        else:
            matched.append(target.isoformat())

    weekend_rows = [item for item in rows if item.timestamp.weekday() >= 5]
    mapped_weekend_dates = {
        candle.timestamp.date().isoformat()
        for target, fragments in grouped.items()
        for candle in fragments
        if candle.timestamp.weekday() >= 5
    }
    return {
        "raw_candles": len(rows),
        "raw_weekend_candles": len(weekend_rows),
        "raw_weekend_candles_mapped": len(mapped_weekend_dates),
        "raw_weekend_candles_unmapped": len(weekend_rows) - len(mapped_weekend_dates),
        "trading_days_reconciled": len(matched),
        "trading_days_mismatched": len(mismatches),
        "unassigned_raw_candles": len(unassigned),
        "matched_trade_dates": matched[:20],
        "mismatch_examples": mismatches[:20],
        "unassigned_examples": unassigned[:20],
        "complete": not mismatches and not unassigned,
        "mapping_rule": (
            "Same-date positive TQBR history keeps a calendar candle on that date; "
            "otherwise a weekend candle maps to the next positive-trade TQBR date "
            "within three calendar days. Fragments are aggregated and checked "
            "against the full trading-day history OHLCV."
        ),
    }


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
