"""MOEX TQBR trading-day bars and raw calendar-session reconciliation.

The research CLI uses one daily OHLCV bar per TQBR TRADEDATE from total-session
history. MOEX weekend additional sessions are part of the next ordinary trading
day; their raw Saturday/Sunday candle fragments are reconciled against that
trading-day history row and are not fed as extra D1 bars.
"""
from __future__ import annotations

from collections import defaultdict
import math
from datetime import date, datetime, time, timedelta

from .core import Candle, validate_candles
from .corporate_actions import classify_history_to_raw_price_factor
from .moex_iss import HistoryRecord


class SessionMappingError(ValueError):
    """Raised when history-backed session mapping is inconsistent."""


# MOEX explicitly designated these 2026 weekday public holidays as additional
# weekend sessions. Each session belongs to the next ordinary trading date.
# Source: https://www.moex.com/n96571
OFFICIAL_WEEKDAY_ADDITIONAL_SESSIONS = {
    date(2026, 2, 23): date(2026, 2, 24),
    date(2026, 5, 1): date(2026, 5, 4),
    date(2026, 6, 12): date(2026, 6, 15),
    date(2026, 11, 4): date(2026, 11, 5),
}


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
    max_next_trading_day_gap: int = 7,
    ticker: str | None = None,
) -> dict:
    """Check calendar-date candle fragments against full TQBR trading-day OHLCV.

    A weekend candle without a same-date history row is assigned to the next
    positive-trade TQBR history date within the bounded calendar gap. All
    fragments assigned to a trade date (weekend plus that date's weekday
    candle) are aggregated and compared with the official history OHLCV.
    History remains the model-input source even when this diagnostic finds a
    mismatch; mismatches are surfaced rather than silently repaired. The audit
    also reports positive-trade history dates that have no corresponding raw
    candle fragments, so incomplete raw-source coverage is not mistaken for a
    fully reconciled sample.
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
        if day in OFFICIAL_WEEKDAY_ADDITIONAL_SESSIONS:
            target = OFFICIAL_WEEKDAY_ADDITIONAL_SESSIONS[day]
            if target not in positive_dates:
                unassigned.append({
                    "calendar_date": day.isoformat(),
                    "reason": (
                        "official weekday additional session target is not a "
                        "positive-trade TQBR date: " + target.isoformat()
                    ),
                })
                continue
        elif same_date is not None:
            if same_date.num_trades is not None and same_date.num_trades > 0:
                target = day
            else:
                unassigned.append({
                    "calendar_date": day.isoformat(),
                    "reason": "same-date TQBR history does not confirm positive trades",
                })
                continue
        elif day.weekday() >= 5 and day >= date(2025, 3, 1):
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
        elif day.weekday() >= 5:
            unassigned.append({
                "calendar_date": day.isoformat(),
                "reason": "pre-launch weekend date lacks same-date TQBR history confirmation",
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
    price_scale_mismatches = []
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
            mismatch = {
                "trade_date": target.isoformat(),
                "reason": "aggregated calendar candles differ from TQBR daily history",
                "fragment_count": len(fragments),
                "differences": differences,
            }
            price_ratios = [
                float(want) / float(got)
                for got, want in zip(actual[:4], expected[:4])
                if float(got) > 0 and float(want) > 0
            ]
            if len(price_ratios) == 4:
                factor = sum(price_ratios) / len(price_ratios)
                same_factor = all(
                    math.isclose(value, factor, rel_tol=1e-6, abs_tol=1e-10)
                    for value in price_ratios
                )
                if same_factor and not math.isclose(
                    factor, 1.0, rel_tol=1e-6, abs_tol=1e-10
                ):
                    classification = classify_history_to_raw_price_factor(
                        ticker, target, factor
                    )
                    volume_ratio = (
                        float(expected[4]) / float(actual[4])
                        if float(actual[4]) > 0 and float(expected[4]) > 0
                        else None
                    )
                    scale_audit = {
                        "trade_date": target.isoformat(),
                        "history_to_raw_ohlc_price_factor": factor,
                        "history_to_raw_volume_factor": volume_ratio,
                        "classification": classification["classification"],
                        "known_event": classification["known_event"],
                        "effective_date": classification["effective_date"],
                        "expected_history_to_raw_price_factor": classification[
                            "expected_history_to_raw_price_factor"
                        ],
                        "matched_ratio_direction": classification.get("matched_ratio_direction"),
                        "source": classification["source"],
                    }
                    mismatch["price_scale_audit"] = scale_audit
                    price_scale_mismatches.append(scale_audit)
            mismatches.append(mismatch)
        else:
            matched.append(target.isoformat())

    weekend_rows = [item for item in rows if item.timestamp.weekday() >= 5]
    mapped_weekend_candles = sum(
        1
        for fragments in grouped.values()
        for candle in fragments
        if candle.timestamp.weekday() >= 5
    )
    weekday_additional_rows = [
        item for item in rows
        if item.timestamp.date() in OFFICIAL_WEEKDAY_ADDITIONAL_SESSIONS
    ]
    mapped_weekday_additional_candles = sum(
        1
        for fragments in grouped.values()
        for candle in fragments
        if candle.timestamp.date() in OFFICIAL_WEEKDAY_ADDITIONAL_SESSIONS
    )
    price_scale_factor_counts = {}
    known_price_basis_match_count = 0
    unexplained_price_scale_mismatch_count = 0
    for item in price_scale_mismatches:
        factor_key = format(item["history_to_raw_ohlc_price_factor"], ".10g")
        price_scale_factor_counts[factor_key] = price_scale_factor_counts.get(factor_key, 0) + 1
        if item["classification"] == "MATCHES_KNOWN_PRE_EVENT_PRICE_BASIS":
            known_price_basis_match_count += 1
        else:
            unexplained_price_scale_mismatch_count += 1

    positive_history_dates = set(positive_dates)
    raw_fragment_history_dates = set(grouped)
    history_dates_without_raw_fragments = sorted(
        day.isoformat() for day in positive_history_dates - raw_fragment_history_dates
    )
    raw_history_date_coverage = (
        len(positive_history_dates & raw_fragment_history_dates) / len(positive_history_dates)
        if positive_history_dates else None
    )
    raw_history_coverage_status = (
        "NO_POSITIVE_HISTORY_DATES" if not positive_history_dates else
        "NO_RAW_CANDLES" if not rows else
        "COMPLETE_DATE_COVERAGE" if not history_dates_without_raw_fragments else
        "PARTIAL_DATE_COVERAGE"
    )
    reconciliation_complete = (
        bool(rows) and not mismatches and not unassigned
        and not history_dates_without_raw_fragments
    )

    # Keep complete reason/field totals in the report; examples remain capped
    # for readability and must never be used as population counts.
    unassigned_reason_counts = {}
    for item in unassigned:
        reason = item["reason"]
        if reason.startswith("official weekday additional session target"):
            category = "OFFICIAL_WEEKDAY_TARGET_NOT_POSITIVE"
        elif reason == "same-date TQBR history does not confirm positive trades":
            category = "SAME_DATE_HISTORY_NOT_POSITIVE"
        elif reason == "no next positive-trade TQBR date within mapping window":
            category = "WEEKEND_NO_NEXT_POSITIVE_DATE"
        elif reason.startswith("pre-launch weekend date"):
            category = "PRELAUNCH_WEEKEND_UNCONFIRMED"
        elif reason == "weekday candle has no same-date TQBR history row":
            category = "WEEKDAY_MISSING_SAME_DATE_HISTORY"
        else:
            category = "OTHER_UNASSIGNED_REASON"
        unassigned_reason_counts[category] = unassigned_reason_counts.get(category, 0) + 1

    mismatch_reason_counts = {}
    mismatch_field_counts = {name: 0 for name in ("open", "high", "low", "close", "volume")}
    for item in mismatches:
        reason = item["reason"]
        category = (
            "HISTORY_ROW_MISSING_OHLCV"
            if reason == "TQBR history row lacks complete OHLCV"
            else "AGGREGATED_OHLCV_DIFFERS"
        )
        mismatch_reason_counts[category] = mismatch_reason_counts.get(category, 0) + 1
        for field in item.get("differences", {}):
            if field in mismatch_field_counts:
                mismatch_field_counts[field] += 1

    mapped_raw_candles = sum(len(fragments) for fragments in grouped.values())
    return {
        "status": "RECONCILED" if reconciliation_complete else (
            "NO_RAW_CANDLES" if not rows else "RECONCILIATION_WITH_CAVEATS"
        ),
        "raw_candles": len(rows),
        "mapped_raw_candles": mapped_raw_candles,
        "unassigned_reason_counts": unassigned_reason_counts,
        "mismatch_reason_counts": mismatch_reason_counts,
        "mismatch_field_counts": mismatch_field_counts,
        "raw_weekend_candles": len(weekend_rows),
        "raw_weekend_candles_mapped": mapped_weekend_candles,
        "raw_weekend_candles_unmapped": len(weekend_rows) - mapped_weekend_candles,
        "raw_weekday_additional_session_candles": len(weekday_additional_rows),
        "raw_weekday_additional_session_candles_mapped": mapped_weekday_additional_candles,
        "raw_weekday_additional_session_candles_unmapped": len(weekday_additional_rows) - mapped_weekday_additional_candles,
        "weekday_additional_session_calendar_source": "https://www.moex.com/n96571",
        "positive_trade_history_dates": len(positive_history_dates),
        "history_dates_with_raw_fragments": len(positive_history_dates & raw_fragment_history_dates),
        "history_trade_dates_without_raw_fragments": len(history_dates_without_raw_fragments),
        "history_trade_dates_without_raw_fragments_examples": history_dates_without_raw_fragments[:20],
        "raw_history_date_coverage_ratio": raw_history_date_coverage,
        "raw_history_coverage_status": raw_history_coverage_status,
        "trading_days_reconciled": len(matched),
        "trading_days_mismatched": len(mismatches),
        "price_scale_mismatch_dates": len(price_scale_mismatches),
        "price_scale_factor_counts": price_scale_factor_counts,
        "known_price_basis_match_count": known_price_basis_match_count,
        "unexplained_price_scale_mismatch_count": unexplained_price_scale_mismatch_count,
        "price_scale_mismatch_examples": price_scale_mismatches[:20],
        "unassigned_raw_candles": len(unassigned),
        "matched_trade_dates": matched[:20],
        "mismatch_examples": mismatches[:20],
        "unassigned_examples": unassigned[:20],
        "complete": reconciliation_complete,
        "mapping_rule": (
            "Same-date positive TQBR history keeps a calendar candle on that date. "
            "Official weekday additional sessions published by MOEX for 2026 map "
            "to their explicitly designated next ordinary trading date. From the "
            "official 2025-03-01 weekend-session launch onward, a weekend candle "
            "without a same-date history row maps to the next positive-trade TQBR "
            "date within seven calendar days. Pre-launch weekend dates require "
            "same-date history confirmation. Fragments are aggregated and checked "
            "against the full trading-day history OHLCV."
        ),
    }


def normalize_daily_candles(
    candles: list[Candle],
    history_records: list[HistoryRecord],
    max_session_date: str | date | None = None,
) -> tuple[list[Candle], dict]:
    """Legacy raw-calendar diagnostic; not used to construct research D1 bars.

    This helper preserves raw candle dates and flags dates without same-date
    history rows. The research CLI instead uses build_trading_day_candles() to
    build one official D1 bar per TQBR TRADEDATE.
    """
    by_date = _records_by_date(history_records)
    rows = validate_candles(candles)
    ceiling = None
    if isinstance(max_session_date, str):
        ceiling = date.fromisoformat(max_session_date)
    elif max_session_date is not None:
        ceiling = max_session_date

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
