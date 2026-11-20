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



def reconcile_cross_source(
    *,
    moex_daily,
    moex_hourly,
    finam_daily,
    finam_hourly,
    tolerance=0.0,
    source_reconciliation=None,
):
    """Compare MOEX and Finam directly while isolating MOEX's 06:00 bucket.

    The 06:00 MOEX bar is reported separately, never merged into or discarded
    from either source. Main-session H1 bars are matched by Moscow-local time.
    Daily checks distinguish raw feed differences from the expected session
    boundary adjustments.
    """
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    md = _index_daily(moex_daily, finam=False)
    fd = _index_daily(finam_daily, finam=True)
    mh, _, _ = _index_hourly(moex_hourly, finam=False)
    fh, _, finam_snapshot_unknown = _index_hourly(finam_hourly, finam=True)

    mdays, fdays = set(md), set(fd)
    common_days = sorted(mdays & fdays)
    # Exclude a truncated first H1 date only when the independent source audit
    # confirms incomplete D1-H1 aggregation on that left boundary.
    source_bad_days = set()
    if source_reconciliation:
        for source in ("moex", "finam"):
            for item in source_reconciliation.get(source, {}).get("comparisons", []):
                if item.get("status") != "MATCHED":
                    source_bad_days.add(date.fromisoformat(item["date"]))
    edge_day = common_days[0] if common_days else None
    excluded_edge_days = {edge_day} if edge_day in source_bad_days else set()
    daily_rows = []
    raw_mismatch_counts = {field: 0 for field in (*PRICE_FIELDS, "volume")}
    adjusted_mismatch_counts = {
        "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0
    }

    for day in common_days:
        moex_bar, finam_bar = md[day], fd[day]
        moex_bars = mh.get(day, [])
        finam_bars = fh.get(day, [])
        moex_06 = next(
            (row for row in moex_bars if _hourly_date_and_hour(row)[1] == 6),
            None,
        )
        moex_main = [
            row for row in moex_bars if _hourly_date_and_hour(row)[1] != 6
        ]
        finam_main = [
            row for row in finam_bars if _hourly_date_and_hour(row)[1] != 6
        ]

        raw = {}
        for field in (*PRICE_FIELDS, "volume"):
            left = float(getattr(moex_bar, field))
            right = float(getattr(finam_bar, field))
            matches = _same(left, right, tolerance)
            if not matches:
                raw_mismatch_counts[field] += 1
            raw[field] = {
                "moex": left,
                "finam": right,
                "difference_moex_minus_finam": left - right,
                "matches": matches,
            }

        if day in excluded_edge_days:
            daily_rows.append({
                "date": day.isoformat(),
                "moex_0600_bucket_present": moex_06 is not None,
                "moex_0600_bucket": (
                    {
                        "open": float(moex_06.open),
                        "high": float(moex_06.high),
                        "low": float(moex_06.low),
                        "close": float(moex_06.close),
                        "volume": float(moex_06.volume),
                    } if moex_06 is not None else None
                ),
                "raw_comparison": raw,
                "session_adjusted_checks": {},
                "status": "EXCLUDED_INCOMPLETE_LEFT_EDGE",
                "reason": "Independent D1-H1 reconciliation reports incomplete hourly coverage on the first common date.",
            })
            continue

        checks = {}
        if moex_06 is not None:
            moex_open_expected = float(moex_06.open)
            finam_open_expected = (
                float(finam_main[0].open) if finam_main else None
            )
            checks["open"] = {
                "moex_expected": moex_open_expected,
                "finam_expected": finam_open_expected,
                "matches": (
                    _same(moex_bar.open, moex_open_expected, tolerance)
                    and finam_open_expected is not None
                    and _same(finam_bar.open, finam_open_expected, tolerance)
                ),
                "explanation": "MOEX D1 opens at its 06:00 bucket; Finam D1 opens at its first main-session H1 bar.",
            }
            expected_high = max(
                float(finam_bar.high), float(moex_06.high)
            )
            expected_low = min(
                float(finam_bar.low), float(moex_06.low)
            )
        else:
            first_moex = float(moex_main[0].open) if moex_main else None
            first_finam = float(finam_main[0].open) if finam_main else None
            checks["open"] = {
                "moex_expected": float(finam_bar.open),
                "finam_expected": float(moex_bar.open),
                "matches": (
                    _same(moex_bar.open, finam_bar.open, tolerance)
                    and (first_moex is None or _same(moex_bar.open, first_moex, tolerance))
                    and (first_finam is None or _same(finam_bar.open, first_finam, tolerance))
                ),
                "explanation": "No MOEX 06:00 bucket; daily opens should agree.",
            }
            expected_high = float(finam_bar.high)
            expected_low = float(finam_bar.low)

        checks["high"] = {
            "moex_expected": expected_high,
            "finam_expected": float(finam_bar.high),
            "matches": _same(moex_bar.high, expected_high, tolerance),
            "explanation": "The MOEX 06:00 bucket may extend the daily high.",
        }
        checks["low"] = {
            "moex_expected": expected_low,
            "finam_expected": float(finam_bar.low),
            "matches": _same(moex_bar.low, expected_low, tolerance),
            "explanation": "The MOEX 06:00 bucket may extend the daily low.",
        }
        checks["close"] = {
            "moex_expected": float(finam_bar.close),
            "finam_expected": float(moex_bar.close),
            "matches": _same(moex_bar.close, finam_bar.close, tolerance),
            "explanation": "Daily closes should be identical.",
        }
        expected_volume = float(finam_bar.volume) + (
            float(moex_06.volume) if moex_06 is not None else 0.0
        )
        checks["volume"] = {
            "moex_expected": expected_volume,
            "finam_expected": float(finam_bar.volume),
            "matches": _same(moex_bar.volume, expected_volume, tolerance),
            "moex_0600_volume": float(moex_06.volume) if moex_06 is not None else 0.0,
            "explanation": "MOEX D1 volume includes the 06:00 bucket; Finam D1 does not.",
        }
        for field, check in checks.items():
            if not check["matches"]:
                adjusted_mismatch_counts[field] += 1

        daily_rows.append({
            "date": day.isoformat(),
            "moex_0600_bucket_present": moex_06 is not None,
            "moex_0600_bucket": (
                {
                    "open": float(moex_06.open),
                    "high": float(moex_06.high),
                    "low": float(moex_06.low),
                    "close": float(moex_06.close),
                    "volume": float(moex_06.volume),
                } if moex_06 is not None else None
            ),
            "raw_comparison": raw,
            "session_adjusted_checks": checks,
            "status": (
                "SESSION_ADJUSTED_MATCH"
                if all(item["matches"] for item in checks.values())
                else "UNEXPLAINED_DIFFERENCE"
            ),
        })

    # Compare all completed main-session H1 bars by Moscow-local timestamp.
    def main_index(rows_by_day):
        indexed = {}
        for rows in rows_by_day.values():
            for row in rows:
                local = _local_datetime(row.timestamp)
                if local.hour == 6:
                    continue
                if local in indexed:
                    raise ValueError(f"Duplicate main-session H1 timestamp: {local.isoformat()}")
                indexed[local] = row
        return indexed

    moex_h1 = main_index(mh)
    finam_h1 = main_index(fh)
    mtimes, ftimes = set(moex_h1), set(finam_h1)
    matched_times = sorted(mtimes & ftimes)
    h1_mismatch_counts = {field: 0 for field in (*PRICE_FIELDS, "volume")}
    h1_mismatches = []
    for timestamp in matched_times:
        left, right = moex_h1[timestamp], finam_h1[timestamp]
        checks = {}
        for field in (*PRICE_FIELDS, "volume"):
            a, b = float(getattr(left, field)), float(getattr(right, field))
            matches = _same(a, b, tolerance)
            if not matches:
                h1_mismatch_counts[field] += 1
            checks[field] = {
                "moex": a, "finam": b,
                "difference_moex_minus_finam": a - b,
                "matches": matches,
            }
        if any(not item["matches"] for item in checks.values()):
            h1_mismatches.append({
                "timestamp_moscow": timestamp.isoformat(),
                "checks": checks,
            })

    edge_moex_only = sorted(item for item in mtimes - ftimes if item.date() in excluded_edge_days)
    edge_finam_only = sorted(item for item in ftimes - mtimes if item.date() in excluded_edge_days)
    unexplained_moex_only = sorted(item for item in mtimes - ftimes if item.date() not in excluded_edge_days)
    unexplained_finam_only = sorted(item for item in ftimes - mtimes if item.date() not in excluded_edge_days)
    daily_ok = (
        len(common_days) == len(mdays) == len(fdays)
        and all(row["status"] in {"SESSION_ADJUSTED_MATCH", "EXCLUDED_INCOMPLETE_LEFT_EDGE"} for row in daily_rows)
    )
    h1_ok = not unexplained_moex_only and not unexplained_finam_only and not h1_mismatches
    has_edge_gap = bool(excluded_edge_days or edge_moex_only or edge_finam_only)
    overall_status = (
        "CROSS_SOURCE_DIFFERENCE" if not (daily_ok and h1_ok)
        else "MATCHED_WITH_EDGE_COVERAGE_GAP" if has_edge_gap
        else "SESSION_ADJUSTED_MATCH"
    )
    return {
        "status": overall_status,
        "daily": {
            "moex_days": len(mdays),
            "finam_days": len(fdays),
            "matched_days": len(common_days),
            "moex_only_dates": sorted(day.isoformat() for day in mdays - fdays),
            "finam_only_dates": sorted(day.isoformat() for day in fdays - mdays),
            "raw_mismatch_counts": raw_mismatch_counts,
            "session_adjusted_mismatch_counts": adjusted_mismatch_counts,
            "moex_0600_days": sum(row["moex_0600_bucket_present"] for row in daily_rows),
            "excluded_incomplete_left_edge_dates": sorted(day.isoformat() for day in excluded_edge_days),
            "adjusted_comparison_days": sum(row["status"] == "SESSION_ADJUSTED_MATCH" for row in daily_rows),
            "comparisons": daily_rows,
        },
        "hourly_main_session": {
            "moex_bars": len(moex_h1),
            "finam_bars": len(finam_h1),
            "matched_timestamps": len(matched_times),
            "moex_only_timestamps": sorted(item.isoformat() for item in mtimes - ftimes),
            "finam_only_timestamps": sorted(item.isoformat() for item in ftimes - mtimes),
            "edge_excluded_moex_only_timestamps": [item.isoformat() for item in edge_moex_only],
            "edge_excluded_finam_only_timestamps": [item.isoformat() for item in edge_finam_only],
            "unexplained_moex_only_timestamps": [item.isoformat() for item in unexplained_moex_only],
            "unexplained_finam_only_timestamps": [item.isoformat() for item in unexplained_finam_only],
            "mismatch_counts": h1_mismatch_counts,
            "mismatches": h1_mismatches,
            "finam_snapshot_unknown_bars_retained": finam_snapshot_unknown,
        },
        "method": (
            "Main-session H1 is compared by Moscow-local timestamp after separating "
            "the 06:00 bucket. D1 raw differences are retained; adjusted checks test "
            "the explicit 06:00 open/high/low/volume boundary without rewriting data."
        ),
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
