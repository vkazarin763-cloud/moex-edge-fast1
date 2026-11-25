"""Read-only Finam-only multi-timeframe candle collection."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .finam_market_data import FinamAPIError, FinamMarketDataClient

MOSCOW = ZoneInfo("Europe/Moscow")
FINAM_FRAMES = {
    "M1": ("TIME_FRAME_M1", 7),
    "M5": ("TIME_FRAME_M5", 30),
    "M15": ("TIME_FRAME_M15", 30),
    "M30": ("TIME_FRAME_M30", 30),
    "H1": ("TIME_FRAME_H1", 30),
    "H2": ("TIME_FRAME_H2", 30),
    "H4": ("TIME_FRAME_H4", 30),
    "H8": ("TIME_FRAME_H8", 30),
    "D1": ("TIME_FRAME_D", 365),
}
ALL_FRAMES = tuple(FINAM_FRAMES)


def _normalize_frames(frames):
    if frames is None:
        return ALL_FRAMES
    if isinstance(frames, str):
        frames = frames.split(",")
    selected = {str(frame).strip().upper() for frame in frames if str(frame).strip()}
    if not selected:
        raise ValueError("At least one timeframe must be selected")
    unknown = sorted(selected - set(ALL_FRAMES))
    if unknown:
        raise ValueError(f"Unsupported Finam timeframes: {', '.join(unknown)}")
    if "D1" not in selected:
        raise ValueError("D1 is required for the latest-signal scanner")
    return tuple(frame for frame in ALL_FRAMES if frame in selected)


DEFAULT_TICKERS = [
    "AFKS", "AFLT", "ALRS", "BSPB", "CBOM", "CHMF", "CNRU", "DOMRF",
    "ENPG", "FLOT", "GAZP", "GMKN", "HEAD", "IRAO", "LKOH", "MAGN",
    "MDMG", "MOEX", "MTSS", "NLMK", "NVTK", "OZON", "PHOR", "PLZL",
    "POSI", "RAGR", "RENI", "ROSN", "RTKM", "RUAL", "SBER", "SBERP",
    "SNGS", "SNGSP", "SVCB", "T", "TATN", "TATNP", "TRNFP", "UGLD",
    "VKCO", "VTBR", "X5", "YDEX",
]


class RefreshingFinamClient:
    """Refresh a short-lived Finam access token once after HTTP 401."""

    def __init__(self, api_token, source_app_id=None):
        self._api_token = api_token
        self._source_app_id = source_app_id
        self._client = FinamMarketDataClient.from_api_token(api_token, source_app_id)

    def fetch_bars(self, *args):
        try:
            return self._client.fetch_bars(*args)
        except FinamAPIError as exc:
            if "HTTP 401" not in str(exc):
                raise
            self._client = FinamMarketDataClient.from_api_token(
                self._api_token, self._source_app_id
            )
            return self._client.fetch_bars(*args)


FINAM_FRAME_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H2": 120, "H4": 240, "H8": 480, "D1": 1440,
}


def _finam_bar_is_complete(timestamp, frame, now_utc):
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return False
    if frame == "D1":
        return timestamp.astimezone(MOSCOW).date() < now_utc.astimezone(MOSCOW).date()
    duration = timedelta(minutes=FINAM_FRAME_MINUTES[frame])
    return timestamp.astimezone(timezone.utc) + duration <= now_utc


def _serialize(rows):
    return [
        {
            "timestamp": row.timestamp.isoformat(),
            "open": float(row.open), "high": float(row.high),
            "low": float(row.low), "close": float(row.close),
            "volume": float(row.volume),
            "is_data_snapshot": row.is_data_snapshot,
        }
        for row in rows
    ]


def collect_multi_timeframe(
    tickers, *, api_token, source_app_id=None, now=None, finam_client=None,
    frames=None,
):
    """Collect each requested timeframe from Finam only; never resample or blend feeds."""
    requested_frames = _normalize_frames(frames)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    client = finam_client or RefreshingFinamClient(api_token, source_app_id)
    results = {}

    for raw_ticker in tickers:
        ticker = str(raw_ticker).strip().upper()
        if not ticker:
            continue
        symbol_result = {}
        for frame, (api_frame, lookback) in FINAM_FRAMES.items():
            if frame not in requested_frames:
                continue
            start, end = current - timedelta(days=lookback), current
            try:
                raw = client.fetch_bars(f"{ticker}@MISX", api_frame, start, end)
                snapshot_eligible = [bar for bar in raw if bar.is_data_snapshot is not True]
                completed = [
                    bar for bar in snapshot_eligible
                    if _finam_bar_is_complete(bar.timestamp, frame, current)
                ]
                symbol_result[frame] = {
                    "source": "Finam Trade API",
                    "status": "OK" if completed else "NO_COMPLETED_BARS",
                    "lookback_calendar_days": lookback,
                    "raw_bars": len(raw),
                    "completed_bars": len(completed),
                    "snapshot_true_excluded": len(raw) - len(snapshot_eligible),
                    "incomplete_bars_excluded": len(snapshot_eligible) - len(completed),
                    "snapshot_unknown_retained": sum(
                        bar.is_data_snapshot is None for bar in completed
                    ),
                    "candles": _serialize(completed),
                }
            except Exception as exc:
                symbol_result[frame] = {
                    "source": "Finam Trade API", "status": "ERROR",
                    "error": str(exc),
                }
        results[ticker] = symbol_result

    summary = {}
    for frame in requested_frames:
        items = [value[frame] for value in results.values()]
        summary[frame] = {
            "source": "Finam Trade API",
            "symbols": len(items),
            "ok": sum(item["status"] == "OK" for item in items),
            "no_completed_bars": sum(item["status"] == "NO_COMPLETED_BARS" for item in items),
            "errors": sum(item["status"] == "ERROR" for item in items),
            "total_completed_bars": sum(item.get("completed_bars", 0) for item in items),
        }
    return {
        "generated_at_utc": current.isoformat(),
        "timezone": "Europe/Moscow",
        "universe": list(results),
        "requested_frames": list(requested_frames),
        "timeframes": summary,
        "results": results,
        "methodology": {
            "source_policy": "All requested D1 and intraday candles are fetched directly from Finam Trade API. No MOEX ISS fallback, resampling, provider merging, interpolation, or gap filling is permitted.",
            "completion_policy": "Finam bars explicitly marked is_data_snapshot=true are excluded. Unknown flags are retained and counted. Every intraday bar must have reached timestamp plus interval duration; D1 bars are included only after their Moscow session date has fully passed.",
            "aggregation_policy": "Native Finam bars only; no resampling, filling, interpolation, or provider blending.",
            "research_isolation": "Current Finam D1/H1 inference data is separate from the frozen pre-holdout strategy research dataset. Post-2026-11-20 outcomes are not used for strategy selection, tuning, calibration, or performance metrics.",
        },
        "safety": "Read-only Finam market-data requests only; no account, order, position, or execution endpoints.",
    }


def main():
    parser = argparse.ArgumentParser(description="Read-only Finam-only multi-timeframe candle collection")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    parser.add_argument("--output", default="moex_edge_multi_timeframe_candles.json")
    parser.add_argument("--frames", default=None,
                        help="Comma-separated Finam timeframes; defaults to all supported Finam frames. D1 is required.")
    args = parser.parse_args()
    token = os.environ.get("FINAM_API_TOKEN", "").strip()
    if not token:
        parser.error("FINAM_API_TOKEN must be supplied through the environment")
    source_app_id = os.environ.get("FINAM_SOURCE_APP_ID", "").strip() or None
    tickers = [item.strip().upper() for item in args.tickers.split(",") if item.strip()]
    frames = [item.strip().upper() for item in args.frames.split(",") if item.strip()] if args.frames else None
    report = collect_multi_timeframe(
        tickers, api_token=token, source_app_id=source_app_id, frames=frames
    )
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print("Finam-only multi-timeframe collection complete:")
    for frame, values in report["timeframes"].items():
        print(
            f"{frame} ({values['source']}): {values['ok']}/{values['symbols']} symbols, "
            f"{values['total_completed_bars']} completed bars, {values['errors']} errors"
        )
    return 0 if any(value["ok"] for value in report["timeframes"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
