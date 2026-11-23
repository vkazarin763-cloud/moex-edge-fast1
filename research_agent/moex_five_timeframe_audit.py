"""Isolated public-MOEX five-timeframe history audit.

Downloads only public TQBR candles; no credentials, broker APIs, or orders.
M15 is aggregated from M1 and H4 from H1. Incomplete bars are discarded.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import zipfile
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

from .core import Candle, validate_candles
from .moex_iss import ISSDataError, fetch_candles

TICKERS = [
    "AFKS", "AFLT", "ALRS", "BSPB", "CBOM", "CHMF", "CNRU", "DOMRF",
    "ENPG", "FLOT", "GAZP", "GMKN", "HEAD", "IRAO", "LKOH", "MAGN",
    "MDMG", "MOEX", "MTSS", "NLMK", "NVTK", "OZON", "PHOR", "PLZL",
    "POSI", "RAGR", "RENI", "ROSN", "RTKM", "RUAL", "SBER", "SBERP",
    "SNGS", "SNGSP", "SVCB", "T", "TATN", "TATNP", "TRNFP", "UGLD",
    "VKCO", "VTBR", "X5", "YDEX",
]
NATIVE = {"M1": 1, "H1": 60, "D1": 24, "W1": 7}
MOSCOW = None  # MOEX ISS candle timestamps are naive exchange-local wall time.


def _write_candles(path: Path, rows: list[Candle]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c in rows:
            writer.writerow([c.timestamp.isoformat(sep=" "), c.open, c.high,
                             c.low, c.close, c.volume])


def _aggregate_group(rows: list[Candle]) -> Candle:
    return Candle(
        rows[0].timestamp, rows[0].open,
        max(c.high for c in rows), min(c.low for c in rows),
        rows[-1].close, sum(c.volume for c in rows),
    )


def aggregate_m15(m1: list[Candle]) -> list[Candle]:
    """Build complete 15-minute bars inside each TQBR continuous session.

    Session anchors: 10:00 and 19:00 Moscow. Bins never bridge the 18:50-19:00
    break. Only groups with all 15 distinct minute starts are emitted.
    """
    rows = validate_candles(m1)
    buckets: dict[datetime, dict[int, Candle]] = defaultdict(dict)
    for c in rows:
        ts = c.timestamp
        if ts.weekday() >= 5:
            continue
        if 10 <= ts.hour < 18 and not (ts.hour == 18 and ts.minute >= 50):
            anchor = ts.replace(hour=10, minute=0, second=0, microsecond=0)
            elapsed = int((ts - anchor).total_seconds() // 60)
        elif 19 <= ts.hour < 24:
            anchor = ts.replace(hour=19, minute=0, second=0, microsecond=0)
            elapsed = int((ts - anchor).total_seconds() // 60)
        else:
            continue
        if elapsed < 0:
            continue
        slot = anchor + timedelta(minutes=(elapsed // 15) * 15)
        buckets[slot][ts.minute] = c
    result = []
    for start, items in sorted(buckets.items()):
        expected = [start + timedelta(minutes=i) for i in range(15)]
        group = [items.get(ts.minute) for ts in expected]
        if all(c is not None for c in group):
            result.append(_aggregate_group(group))
    return validate_candles(result) if result else []


def aggregate_h4(h1: list[Candle]) -> list[Candle]:
    """Build complete 4-hour bars anchored at 10:00, 14:00 and 19:00.

    Each group is session-contained: 10-14, 14-18 and 19-23 Moscow.
    No synthetic candles or cross-break aggregation.
    """
    rows = validate_candles(h1)
    buckets: dict[datetime, dict[datetime, Candle]] = defaultdict(dict)
    for c in rows:
        ts = c.timestamp
        if ts.weekday() >= 5 or ts.minute != 0:
            continue
        if ts.hour in range(10, 14):
            start = ts.replace(hour=10, minute=0, second=0, microsecond=0)
        elif ts.hour in range(14, 18):
            start = ts.replace(hour=14, minute=0, second=0, microsecond=0)
        elif ts.hour in range(19, 23):
            start = ts.replace(hour=19, minute=0, second=0, microsecond=0)
        else:
            continue
        buckets[start][ts] = c
    result = []
    for start, items in sorted(buckets.items()):
        group = [items.get(start + timedelta(hours=i)) for i in range(4)]
        if all(c is not None for c in group):
            result.append(_aggregate_group(group))
    return validate_candles(result) if result else []


def audit_rows(rows: list[Candle], timeframe: str) -> dict:
    if not rows:
        return {"bars": 0, "status": "NO_DATA"}
    # fetch_candles already rejects duplicate/out-of-order timestamps and
    # invalid OHLCV. Revalidate after any resampling.
    validate_candles(rows)
    stamps = [c.timestamp for c in rows]
    gaps = []
    for a, b in zip(stamps, stamps[1:]):
        delta = b - a
        expected = {"M1": 1, "M15": 15, "H1": 60, "H4": 240, "D1": None, "W1": None}[timeframe]
        if expected and delta > timedelta(minutes=expected):
            gaps.append({"from": a.isoformat(), "to": b.isoformat(),
                         "minutes": int(delta.total_seconds() // 60)})
    return {
        "bars": len(rows), "status": "OK",
        "first": stamps[0].isoformat(), "last": stamps[-1].isoformat(),
        "weekend_bars": sum(ts.weekday() >= 5 for ts in stamps),
        "gap_count": len(gaps), "largest_gaps": gaps[:20],
        "ohlc_valid": True, "timestamps_unique_ordered": True,
    }


def run(date_from: str, date_till: str, output: Path, tickers: list[str]) -> dict:
    date.fromisoformat(date_from)
    date.fromisoformat(date_till)
    if date_from > date_till:
        raise ValueError("date_from must be <= date_till")
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "source": "public MOEX ISS TQBR candles; delayed public market data",
        "date_from": date_from, "date_till": date_till,
        "universe": tickers, "native_intervals": NATIVE,
        "derived_intervals": {"M15": "M1", "H4": "H1"},
        "aggregation": {
            "timezone": "Europe/Moscow (MOEX ISS naive timestamps)",
            "M15": "complete 15x M1 groups anchored 10:00 and 19:00; no session-break crossing",
            "H4": "complete H1 groups 10:00-14:00, 14:00-18:00, 19:00-23:00",
            "incomplete_groups": "discarded; no interpolation",
        },
        "symbols": {}, "totals": {k: 0 for k in ("M1", "M15", "H1", "H4", "D1", "W1")},
    }
    for ticker in tickers:
        symbol = {}
        native_rows = {}
        for frame, interval in NATIVE.items():
            try:
                rows = fetch_candles(ticker, date_from, date_till, interval=interval)
                native_rows[frame] = rows
                symbol[frame] = audit_rows(rows, frame)
                _write_candles(output / f"{ticker}_{frame}.csv", rows)
                report["totals"][frame] += len(rows)
            except Exception as exc:
                symbol[frame] = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
            time.sleep(0.15)
        if "M1" in native_rows:
            rows = aggregate_m15(native_rows["M1"])
            symbol["M15"] = audit_rows(rows, "M15")
            if rows:
                _write_candles(output / f"{ticker}_M15.csv", rows)
                report["totals"]["M15"] += len(rows)
        else:
            symbol["M15"] = {"status": "BLOCKED_NO_M1", "bars": 0}
        if "H1" in native_rows:
            rows = aggregate_h4(native_rows["H1"])
            symbol["H4"] = audit_rows(rows, "H4")
            if rows:
                _write_candles(output / f"{ticker}_H4.csv", rows)
                report["totals"]["H4"] += len(rows)
        else:
            symbol["H4"] = {"status": "BLOCKED_NO_H1", "bars": 0}
        report["symbols"][ticker] = symbol
        print(f"{ticker}: " + ", ".join(
            f"{tf}={symbol.get(tf, {}).get('bars', 0)}:{symbol.get(tf, {}).get('status')}"
            for tf in ("W1", "D1", "H4", "H1", "M15")
        ), flush=True)

    for frame in ("M1", "M15", "H1", "H4", "D1", "W1"):
        report["totals"][frame] = int(report["totals"][frame])
    report["coverage"] = {
        tf: sum(s.get(tf, {}).get("status") == "OK" and s.get(tf, {}).get("bars", 0) > 0
                for s in report["symbols"].values())
        for tf in ("W1", "D1", "H4", "H1", "M15")
    }
    report["all_44_have_all_frames"] = all(
        all(report["symbols"][t].get(tf, {}).get("status") == "OK"
            and report["symbols"][t].get(tf, {}).get("bars", 0) > 0
            for tf in ("W1", "D1", "H4", "H1", "M15"))
        for t in tickers
    )
    (output / "history_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    archive = output.parent / "moex_five_timeframe_history.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(output.glob("*")):
            zf.write(path, arcname=f"moex_five_timeframe_history/{path.name}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-date", default="2025-11-20")
    parser.add_argument("--till-date", default=date.today().isoformat())
    parser.add_argument("--output", default="artifacts/moex_five_timeframe_history")
    parser.add_argument("--tickers", default=",".join(TICKERS))
    args = parser.parse_args()
    report = run(args.from_date, args.till_date, Path(args.output),
                 [x.strip().upper() for x in args.tickers.split(",") if x.strip()])
    print(json.dumps({
        "coverage": report["coverage"], "totals": report["totals"],
        "all_44_have_all_frames": report["all_44_have_all_frames"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
