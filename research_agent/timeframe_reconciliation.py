"""Read-only reconciliation of daily candles against hourly source bars.

This module diagnoses aggregation/session-scope differences. It never merges feeds,
rewrites candles, or changes strategy/holdout inputs.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")
PRICE_FIELDS = ("open", "high", "low", "close")


def _local_datetime(timestamp):
    if timestamp.tzinfo is None:
        return timestamp
    return timestamp.astimezone(MOSCOW).replace(tzinfo=None)


def _daily_date(row, *, finam):
    timestamp = row.timestamp
    return timestamp.astimezone(MOSCOW).date() if finam and timestamp.tzinfo else timestamp.date()


def _hourly_date_and_hour(row):
    local = _local_datetime(row.timestamp)
    return local.date(), local.hour


def _index_daily(rows, *, finam):
    indexed = {}
    for row in rows:
        day = _daily_date(row, finam=finam)
        if day in indexed:
            raise ValueError(f"Duplicate daily candle for {day.isoformat()}")
        indexed[day] = row
    return indexed


def _index_hourly(rows, *, finam):
    indexed = defaultdict(list)
    seen = set()
    snapshot_true = 0
    snapshot_unknown = 0
    for row in rows:
        if finam:
            snapshot = getattr(row, "is_data_snapshot", None)
            if snapshot is True:
                snapshot_true += 1
                continue
            if snapshot is None:
                snapshot_unknown += 1
        day, hour = _hourly_date_and_hour(row)
        local = _local_datetime(row.timestamp)
        key = (day, local)
        if key in seen:
            raise ValueError(f"Duplicate hourly candle for {local.isoformat()}")
        seen.add(key)
        indexed[day].append(row)
    for values in indexed.values():
        values.sort(key=lambda row: _local_datetime(row.timestamp))
    return indexed, snapshot_true, snapshot_unknown


def _same(actual, expected, tolerance):
    return abs(float(actual) - float(expected)) <= tolerance


def reconcile_daily_to_hourly(
    daily_rows,
    hourly_rows,
    *,
    source,
    finam=False,
    opening_bucket_hour=None,
    excluded_hours=(),
    tolerance=0.0,
):
    """Compare one source's D1 bars with its own H1 aggregation by local date.

    For MOEX, opening_bucket_hour=6 lets D1 open be checked against the
    06:00 bucket when present; all hourly buckets remain included in volume
    and extrema aggregation. For Finam, excluded_hours={6} reflects the
    observed D1/H1 boundary where D1 starts at the first main-session H1 bar.
    """
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    daily = _index_daily(daily_rows, finam=finam)
    hourly, snapshots_true, snapshots_unknown = _index_hourly(hourly_rows, finam=finam)
    daily_dates, hourly_dates = set(daily), set(hourly)
    comparisons = []

    for day in sorted(daily_dates):
        daily_bar = daily[day]
        all_bars = hourly.get(day, [])
        bars = [
            row for row in all_bars
            if _hourly_date_and_hour(row)[1] not in set(excluded_hours)
        ]
        if not bars:
            comparisons.append({
                "date": day.isoformat(),
                "status": "NO_ELIGIBLE_H1_BARS",
                "daily_values": {
                    field: float(getattr(daily_bar, field))
                    for field in (*PRICE_FIELDS, "volume")
                },
                "h1_bars_total": len(all_bars),
                "h1_bars_eligible": 0,
                "checks": {},
            })
            continue

        opening_bar = None
        if opening_bucket_hour is not None:
            opening_bar = next(
                (row for row in all_bars
                 if _hourly_date_and_hour(row)[1] == opening_bucket_hour),
                None,
            )
        if opening_bar is None:
            opening_bar = bars[0]

        aggregation_bars = all_bars if opening_bucket_hour is not None else bars
        aggregate = {
            "open": float(opening_bar.open),
            "high": max(float(row.high) for row in aggregation_bars),
            "low": min(float(row.low) for row in aggregation_bars),
            "close": float(bars[-1].close),
            "volume": sum(float(row.volume) for row in aggregation_bars),
        }
        checks = {}
        for field in (*PRICE_FIELDS, "volume"):
            actual = float(getattr(daily_bar, field))
            expected = aggregate[field]
            checks[field] = {
                "daily": actual,
                "h1_aggregate": expected,
                "difference": actual - expected,
                "matches": _same(actual, expected, tolerance),
            }
        comparisons.append({
            "date": day.isoformat(),
            "status": (
                "MATCHED" if all(item["matches"] for item in checks.values())
                else "AGGREGATION_DIFFERENCE"
            ),
            "daily_values": {
                field: float(getattr(daily_bar, field))
                for field in (*PRICE_FIELDS, "volume")
            },
            "h1_bars_total": len(all_bars),
            "h1_bars_eligible": len(bars),
            "opening_bucket_present": opening_bar is not bars[0] or (
                opening_bucket_hour is not None
                and _hourly_date_and_hour(opening_bar)[1] == opening_bucket_hour
            ),
            "h1_first_eligible_timestamp_local": _local_datetime(bars[0].timestamp).isoformat(),
            "h1_last_eligible_timestamp_local": _local_datetime(bars[-1].timestamp).isoformat(),
            "checks": checks,
        })

    matched = [item for item in comparisons if item["status"] == "MATCHED"]
    no_h1 = [item for item in comparisons if item["status"] == "NO_ELIGIBLE_H1_BARS"]
    differences = [item for item in comparisons if item["status"] == "AGGREGATION_DIFFERENCE"]
    return {
        "source": source,
        "status": (
            "NO_DAILY_BARS" if not daily_dates else
            "NO_H1_BARS" if not hourly_dates else
            "RECONCILED" if len(matched) == len(daily_dates) else
            "PARTIAL_OR_DIFFERING"
        ),
        "daily_days": len(daily_dates),
        "h1_days": len(hourly_dates),
        "matched_days": len(matched),
        "different_days": len(differences),
        "daily_days_without_h1": [item["date"] for item in no_h1],
        "h1_only_dates": sorted(day.isoformat() for day in hourly_dates - daily_dates),
        "finam_snapshot_true_bars_excluded": snapshots_true,
        "finam_snapshot_unknown_bars_retained": snapshots_unknown,
        "tolerance": tolerance,
        "comparisons": comparisons,
    }


def reconcile_moex_and_finam(
    *,
    moex_daily,
    moex_hourly,
    finam_daily,
    finam_hourly,
    tolerance=0.0,
):
    """Return independent MOEX and Finam D1↔H1 diagnostics; no cross-feed merge."""
    return {
        "comparison_basis": "independent D1-to-H1 aggregation by Europe/Moscow date",
        "moex": reconcile_daily_to_hourly(
            moex_daily, moex_hourly, source="MOEX ISS",
            opening_bucket_hour=6, tolerance=tolerance,
        ),
        "finam": reconcile_daily_to_hourly(
            finam_daily, finam_hourly, source="Finam Trade API",
            finam=True, excluded_hours={6}, tolerance=tolerance,
        ),
        "safety": (
            "Read-only diagnostics. Source candles are not modified or merged; "
            "no strategy, cohort, holdout, broker, or execution state is changed."
        ),
    }
