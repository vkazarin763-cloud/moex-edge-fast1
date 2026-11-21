"""Read-only multi-timeframe candle collection, isolated from frozen D1 research."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .finam_market_data import FinamAPIError, FinamMarketDataClient, create_access_token
from .moex_iss import fetch_candles

MOSCOW = ZoneInfo("Europe/Moscow")
# Finam's documented lookback limits are enforced by FinamMarketDataClient.
FINAM_FRAMES = {
    "M1": ("TIME_FRAME_M1", 7),
    "M5": ("TIME_FRAME_M5", 30),
    "M15": ("TIME_FRAME_M15", 30),
    "M30": ("TIME_FRAME_M30", 30),
    "H2": ("TIME_FRAME_H2", 30),
    "H4": ("TIME_FRAME_H4", 30),
    "H8": ("TIME_FRAME_H8", 30),
}
# Native MOEX ISS candle intervals: 10m, weekly, monthly, quarterly.
MOEX_FRAMES = {"M10": 10, "W1": 7, "MN": 31, "QR": 4}
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
    moex_fetcher=fetch_candles, finam_client=None,
):
    """Collect each interval independently; never resample or merge providers."""
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
            start = current - timedelta(days=lookback)
            try:
                raw = client.fetch_bars(f"{ticker}@MISX", api_frame, start, current)
                completed = [bar for bar in raw if bar.is_data_snapshot is not True]
                symbol_result[frame] = {
                    "source": "Finam",
                    "status": "OK" if completed else "NO_COMPLETED_BARS",
                    "lookback_calendar_days": lookback,
                    "raw_bars": len(raw),
                    "completed_bars": len(completed),
                    "snapshot_true_excluded": len(raw) - len(completed),
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
        results[ticker] = symbol_result

    summary = {}
    for frame in (*FINAM_FRAMES.keys(), *MOEX_FRAMES.keys()):
        items = [value[frame] for value in results.values()]
        summary[frame] = {
            "source": items[0]["source"] if items else (
                "Finam" if frame in FINAM_FRAMES else "MOEX ISS"
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
        "timeframes": summary,
        "results": results,
        "methodology": {
            "source_policy": "Finam and MOEX ISS candles are kept as separate feeds.",
            "completion_policy": "Finam bars explicitly marked is_data_snapshot=true are excluded; unknown flags are retained and counted. MOEX M10 bars are included only after their 10-minute interval has ended; W1/MN/QR bars are included only after the corresponding calendar period has ended.",
            "aggregation_policy": "No resampling, filling, interpolation, provider merging, or strategy use.",
            "research_isolation": "This artifact does not modify the frozen D1 research dataset, candidate cohort, holdout, or trading configuration.",
        },
        "safety": "Read-only public market-data requests only; no account, order, position, or execution endpoints.",
    }


def main():
    parser = argparse.ArgumentParser(description="Read-only multi-timeframe MOEX/Finam candle collection")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    parser.add_argument("--output", default="moex_edge_multi_timeframe_candles.json")
    args = parser.parse_args()
    token = os.environ.get("FINAM_API_TOKEN", "").strip()
    if not token:
        parser.error("FINAM_API_TOKEN must be supplied through the environment")
    source_app_id = os.environ.get("FINAM_SOURCE_APP_ID", "").strip() or None
    tickers = [item.strip().upper() for item in args.tickers.split(",") if item.strip()]
    report = collect_multi_timeframe(
        tickers, api_token=token, source_app_id=source_app_id
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
