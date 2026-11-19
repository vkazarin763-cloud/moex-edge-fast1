"""Descriptive candle-quality audit for the read-only MOEX research pipeline.

This module deliberately does not infer missing exchange sessions from weekdays:
MOEX holidays, suspensions, IPO dates and security-specific trading calendars can
all create legitimate date gaps. Such gaps are reported for review, not labelled
as missing candles.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .core import Candle, validate_candles


def candle_quality_report(
    candles: list[Candle],
    requested_from: str | None = None,
    requested_till: str | None = None,
    warmup_bars: int = 200,
    preferred_min_bars: int = 500,
) -> dict[str, Any]:
    """Return validated-series diagnostics without making calendar assumptions."""
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
    weekend = sum(c.timestamp.weekday() >= 5 for c in rows)
    has_caveats = (
        gaps or zero_volume or weekend
        or history_status != "PREFERRED_HISTORY_LENGTH"
        or boundary_missing or outside_requested_range
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
        "calendar_gap_candidates": gaps,
        "calendar_gap_count": len(gaps),
        "exchange_calendar_verified": False,
        "calendar_caveat": (
            "Weekday dates inside gaps are not classified as missing sessions: "
            "MOEX holidays, listing dates, suspensions and security-specific "
            "trading schedules have not been checked."
        ),
        "history_status": history_status,
        "warmup_bars_required": warmup_bars,
        "preferred_min_bars": preferred_min_bars,
    }
