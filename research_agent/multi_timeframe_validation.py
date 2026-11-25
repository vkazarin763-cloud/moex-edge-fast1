"""Timestamp normalization and no-lookahead validation for independent candle feeds."""
from __future__ import annotations

import argparse
import json
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")
FINAM_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H2": 120, "H4": 240, "H8": 480,
}


def _parse_utc(value: str, source: str) -> datetime:
    if source != "Finam Trade API":
        raise ValueError("only Finam Trade API candle sources are accepted")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Finam timestamps must be timezone-aware")
    return stamp.astimezone(timezone.utc)


def candle_end_utc(timestamp: str, source: str, frame: str) -> datetime:
    start = _parse_utc(timestamp, source)
    if frame in FINAM_MINUTES:
        return start + timedelta(minutes=FINAM_MINUTES[frame])
    if frame == "D1":
        local = start.astimezone(MOSCOW)
        next_midnight = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return next_midnight.astimezone(timezone.utc)
    raise ValueError(f"unsupported Finam timeframe: {frame}")


def validate_multi_timeframe_report(report: dict, *, as_of: datetime | None = None) -> dict:
    """Validate chronology/OHLC and build a latest-closed-bar snapshot per frame."""
    generated = datetime.fromisoformat(report["generated_at_utc"].replace("Z", "+00:00"))
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ValueError("generated_at_utc must be timezone-aware")
    generated = generated.astimezone(timezone.utc)
    cutoff = (as_of or generated).astimezone(timezone.utc)
    if cutoff > generated:
        raise ValueError("as_of cannot be later than report generation time")

    issues = []
    frame_summary = {}
    snapshots = {}
    frame_names = list(report.get("timeframes", {}))
    for frame in frame_names:
        frame_summary[frame] = {"symbols": 0, "bars": 0, "empty_symbols": 0}

    for symbol, symbol_data in report.get("results", {}).items():
        snapshots[symbol] = {}
        for frame in frame_names:
            item = symbol_data.get(frame, {})
            if item.get("source") != "Finam Trade API":
                issues.append({"symbol": symbol, "frame": frame, "type": "non_finam_source"})
                continue
            candles = item.get("candles", [])
            if item.get("status") == "ERROR":
                issues.append({"symbol": symbol, "frame": frame, "type": "source_error"})
                continue
            if not candles:
                frame_summary[frame]["empty_symbols"] += 1
                continue

            frame_summary[frame]["symbols"] += 1
            frame_summary[frame]["bars"] += len(candles)
            previous = None
            latest = None
            seen = set()
            for index, candle in enumerate(candles):
                try:
                    start = _parse_utc(candle["timestamp"], item["source"])
                    end = candle_end_utc(candle["timestamp"], item["source"], frame)
                    values = [float(candle[key]) for key in ("open", "high", "low", "close", "volume")]
                    open_, high, low, close, volume = values
                    if not all(__import__("math").isfinite(value) for value in values):
                        raise ValueError("non-finite OHLCV")
                    if high < max(open_, close, low) or low > min(open_, close, high) or volume < 0:
                        raise ValueError("invalid OHLCV bounds")
                    if start in seen:
                        issues.append({"symbol": symbol, "frame": frame, "index": index, "type": "duplicate_timestamp"})
                    if previous is not None and start <= previous:
                        issues.append({"symbol": symbol, "frame": frame, "index": index, "type": "non_monotonic_timestamp"})
                    if end > cutoff:
                        issues.append({"symbol": symbol, "frame": frame, "index": index, "type": "unclosed_or_future_bar"})
                    seen.add(start)
                    previous = start
                    if end <= cutoff:
                        latest = {
                            "timestamp": start.isoformat(),
                            "end_utc": end.isoformat(),
                            "age_minutes": round((cutoff - end).total_seconds() / 60, 2),
                        }
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    issues.append({"symbol": symbol, "frame": frame, "index": index, "type": "invalid_bar", "detail": str(exc)})
            snapshots[symbol][frame] = latest

    return {
        "generated_at_utc": generated.isoformat(),
        "as_of_utc": cutoff.isoformat(),
        "status": "PASS" if not issues else "FAIL",
        "symbol_count": len(report.get("results", {})),
        "frame_summary": frame_summary,
        "latest_closed_bars": snapshots,
        "issue_count": len(issues),
        "issues": issues,
        "methodology": "Only Finam Trade API sources are accepted. Finam timestamps are timezone-aware UTC; bar ends are calculated from native interval definitions. Only bars whose end is at or before as_of_utc enter latest_closed_bars.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Finam-only MOEX EDGE multi-timeframe candle chronology")
    parser.add_argument("--input", default="moex_edge_multi_timeframe_candles.json")
    parser.add_argument("--output", default="moex_edge_multi_timeframe_validation.json")
    args = parser.parse_args()
    report = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = validate_multi_timeframe_report(report)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Multi-timeframe validation: {result['status']}; {result['issue_count']} issues; {result['symbol_count']} symbols")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
