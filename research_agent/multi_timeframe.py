"""Read-only multi-timeframe candle collection, isolated from frozen D1 research."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .finam_market_data import FinamAPIError, FinamMarketDataClient, create_access_token
from .moex_iss import fetch_candles, fetch_history_records

MOSCOW = ZoneInfo("Europe/Moscow")
# Finam's documented lookback limits are enforced by FinamMarketDataClient.
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
# Native MOEX ISS candle intervals: 10m, weekly, monthly, quarterly.
MOEX_FRAMES = {"M10": 10, "W1": 7, "MN": 31, "QR": 4}
ALL_FRAMES = (*FINAM_FRAMES.keys(), *MOEX_FRAMES.keys(), "D1")


def _normalize_frames(frames):
    """Select supported feeds while preserving the stable default order."""
    if frames is None:
        return ALL_FRAMES
    if isinstance(frames, str):
        frames = frames.split(",")
    selected = {
        str(frame).strip().upper()
        for frame in frames
        if str(frame).strip()
    }
    if not selected:
        raise ValueError("At least one timeframe must be selected")
    unknown = sorted(selected - set(ALL_FRAMES))
    if unknown:
        raise ValueError(f"Unsupported timeframes: {', '.join(unknown)}")
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
            # Re-authenticate once; if the retry still fails, surface the
            # original symbol/timeframe failure to the caller.
            self._client = FinamMarketDataClient.from_api_token(
                self._api_token, self._source_app_id
            )
            return self._client.fetch_bars(*args)


FINAM_FRAME_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H2": 120, "H4": 240, "H8": 480, "D1": 1440,
}


def _finam_bar_is_complete(timestamp, frame, now_utc):
    """Finam intraday timestamps mark bar starts; require the full interval to end."""
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return False
    if frame == "D1":
        return timestamp.astimezone(MOSCOW).date() < now_utc.astimezone(MOSCOW).date()
    duration = timedelta(minutes=FINAM_FRAME_MINUTES[frame])
    return timestamp.astimezone(timezone.utc) + duration <= now_utc


def _moex_bar_is_complete(timestamp, frame, now_moscow):
    """MOEX ISS timestamps are exchange-local naive datetimes."""
    if timestamp.tzinfo is not None and timestamp.utcoffset() is not None:
        local_stamp = timestamp.astimezone(MOSCOW).replace(tzinfo=None)
    else:
        local_stamp = timestamp
    if frame == "M10":
        return local_stamp + timedelta(minutes=10) <= now_moscow
    start = local_stamp.date()
    if frame == "W1":
        period_end = start + timedelta(days=7)
    elif frame == "MN":
        year, month = start.year, start.month
        period_end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    else:  # QR
        month_index = start.month - 1 + 3
        year = start.year + month_index // 12
        month = month_index % 12 + 1
        period_end = date(year, month, 1)
    return period_end <= now_moscow.date()


def _serialize(rows, *, snapshot_field=False):
    result = []
    for row in rows:
        item = {
            "timestamp": row.timestamp.isoformat(),
            "open": float(row.open), "high": float(row.high),
            "low": float(row.low), "close": float(row.close),
            "volume": float(row.volume),
        }
        if snapshot_field:
            item["is_data_snapshot"] = row.is_data_snapshot
        result.append(item)
    return result


def collect_multi_timeframe(
    tickers, *, api_token, source_app_id=None, now=None,
    moex_fetcher=fetch_candles, moex_history_fetcher=fetch_history_records, finam_client=None,
    frames=None,
):
    """Collect each interval independently; never resample or merge providers."""
    requested_frames = _normalize_frames(frames)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    local_today = current.astimezone(MOSCOW).date()
    client = finam_client or RefreshingFinamClient(api_token, source_app_id)
    now_moscow = current.astimezone(MOSCOW).replace(tzinfo=None)
    results = {}

    for raw_ticker in tickers:
        ticker = str(raw_ticker).strip().upper()
        if not ticker:
            continue
        symbol_result = {}
        # Finam intraday bars: preserve snapshot metadata and exclude only
        # explicitly marked snapshots from the completed-bar collection.
        for frame, (api_frame, lookback) in FINAM_FRAMES.items():
            if frame not in requested_frames:
                continue
            if frame == "D1":
                end = current.replace(hour=0, minute=0, second=0, microsecond=0)
                start = end - timedelta(days=lookback)
            else:
                start, end = current - timedelta(days=lookback), current
            try:
                raw = client.fetch_bars(f"{ticker}@MISX", api_frame, start, end)
                snapshot_eligible = [bar for bar in raw if bar.is_data_snapshot is not True]
                completed = [
                    bar for bar in snapshot_eligible
                    if _finam_bar_is_complete(bar.timestamp, frame, current)
                ]
                symbol_result[frame] = {
                    "source": "Finam",
                    "status": "OK" if completed else "NO_COMPLETED_BARS",
                    "lookback_calendar_days": lookback,
                    "raw_bars": len(raw),
                    "completed_bars": len(completed),
                    "snapshot_true_excluded": len(raw) - len(snapshot_eligible),
                    "incomplete_bars_excluded": len(snapshot_eligible) - len(completed),
                    "snapshot_unknown_retained": sum(
                        bar.is_data_snapshot is None for bar in completed
                    ),
                    "candles": _serialize(completed, snapshot_field=True),
                }
            except Exception as exc:
                symbol_result[frame] = {
                    "source": "Finam", "status": "ERROR",
                    "error": str(exc),
                }

        # MOEX ISS native intervals. Intraday M10 uses a recent window;
        # W1/MN/QR retain a longer context for trend analysis.
        for frame, interval in MOEX_FRAMES.items():
            if frame not in requested_frames:
                continue
            lookback = 30 if frame == "M10" else 365 * 5
            start_date = (local_today - timedelta(days=lookback)).isoformat()
            end_date = local_today.isoformat()
            try:
                rows = moex_fetcher(
                    ticker, start_date, end_date, interval=interval, board="TQBR"
                )
                completed = [
                    row for row in rows
                    if _moex_bar_is_complete(row.timestamp, frame, now_moscow)
                ]
                symbol_result[frame] = {
                    "source": "MOEX ISS",
                    "status": "OK" if completed else "NO_COMPLETED_BARS",
                    "lookback_calendar_days": lookback,
                    "raw_bars": len(rows), "completed_bars": len(completed),
                    "incomplete_bars_excluded": len(rows) - len(completed),
                    "candles": _serialize(completed),
                }
            except Exception as exc:
                symbol_result[frame] = {
                    "source": "MOEX ISS", "status": "ERROR",
                    "error": str(exc),
                }
        # D1 is collected directly from Finam above, alongside H1.
        results[ticker] = symbol_result

    summary = {}
    for frame in requested_frames:
        items = [value[frame] for value in results.values()]
        summary[frame] = {
            "source": items[0]["source"] if items else (
                "Finam" if frame in FINAM_FRAMES else ("Finam" if frame == "D1" else "MOEX ISS")
            ),
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
            "source_policy": "D1 and H1 signal candles are fetched directly from Finam; no MOEX ISS fallback, resampling, or provider merging is used for these signal inputs. Optional non-signal intervals retain their explicitly labeled native MOEX ISS source.",
            "completion_policy": "Finam bars explicitly marked is_data_snapshot=true are excluded; unknown flags are retained and counted. All Finam intraday bars are also required to have reached timestamp plus interval duration. MOEX M10 bars are included only after their 10-minute interval has ended; W1/MN/QR bars are included only after the corresponding calendar period has ended. Finam D1 bars are included only after their Moscow calendar date has fully passed; explicitly marked snapshots and incomplete/current-date bars are excluded and counted.",
            "aggregation_policy": "No resampling, filling, interpolation, provider merging, or strategy use.",
            "research_isolation": "This artifact does not modify the frozen D1 research dataset, candidate cohort, holdout, or trading configuration.",
        },
        "safety": "Read-only public market-data requests only; no account, order, position, or execution endpoints.",
    }


def main():
    parser = argparse.ArgumentParser(description="Read-only multi-timeframe MOEX/Finam candle collection")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    parser.add_argument("--output", default="moex_edge_multi_timeframe_candles.json")
    parser.add_argument("--frames", default=None,
                        help="Comma-separated timeframes; defaults to all supported frames. D1 is required.")
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
    print("Multi-timeframe collection complete:")
    for frame, values in report["timeframes"].items():
        print(
            f"{frame} ({values['source']}): {values['ok']}/{values['symbols']} symbols, "
            f"{values['total_completed_bars']} completed bars, "
            f"{values['errors']} errors"
        )
    return 0 if any(value["ok"] for value in report["timeframes"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
