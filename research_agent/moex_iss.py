"""Read-only MOEX ISS candle and historical-record ingestion.

No authentication, broker access, or order submission is used.
"""
from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .core import Candle, validate_candles

ISS_BASE = "https://iss.moex.com/iss"


class ISSDataError(RuntimeError):
    """Raised when MOEX ISS returns incomplete or malformed data."""


@dataclass(frozen=True)
class HistoryRecord:
    """One official TQBR end-of-day history row for a security."""
    trade_date: date
    num_trades: int | None


def _get_json(url: str, timeout: int = 20, retries: int = 3,
              sleep=time.sleep) -> dict:
    last_error = None
    for attempt in range(retries):
        try:
            request = Request(url, headers={"User-Agent": "MOEX-EDGE-Research-Agent/1.0"})
            with urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise ISSDataError(f"MOEX ISS HTTP status {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ISSDataError("MOEX ISS response is not a JSON object")
                return payload
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                sleep(min(2 ** attempt, 4))
    raise ISSDataError(f"MOEX ISS request failed after {retries} attempts: {last_error}")


def fetch_candles(ticker: str, date_from: str, date_till: str, interval: int = 60,
                  board: str = "TQBR", timeout: int = 20, retries: int = 3,
                  getter=_get_json) -> list[Candle]:
    """Fetch all available candles for one symbol/timeframe; gaps are preserved."""
    ticker = ticker.strip().upper()
    board = board.strip().upper()
    if not ticker or not board:
        raise ValueError("ticker and board are required")
    if interval not in (1, 10, 60, 24, 7, 31, 4):
        raise ValueError("Unsupported MOEX candle interval")
    start = 0
    result: list[Candle] = []
    seen = set()
    while True:
        path = (
            f"{ISS_BASE}/engines/stock/markets/shares/boards/{quote(board)}/"
            f"securities/{quote(ticker)}/candles.json"
        )
        query = urlencode({
            "from": date_from, "till": date_till, "interval": interval,
            "start": start, "iss.meta": "off", "iss.reverse": "false",
        })
        payload = getter(f"{path}?{query}", timeout=timeout, retries=retries)
        block = payload.get("candles")
        if not isinstance(block, dict) or not isinstance(block.get("columns"), list) or not isinstance(block.get("data"), list):
            raise ISSDataError("MOEX ISS response lacks a valid candles block")
        columns = block["columns"]
        required = {"begin", "open", "high", "low", "close", "volume"}
        if not required.issubset(columns):
            raise ISSDataError(f"MOEX ISS candle columns missing: {sorted(required - set(columns))}")
        idx = {name: columns.index(name) for name in required}
        rows = block["data"]
        for row in rows:
            try:
                ts = datetime.fromisoformat(str(row[idx["begin"]]).replace("Z", "+00:00"))
                candle = Candle(ts, *(float(row[idx[k]]) for k in ("open", "high", "low", "close", "volume")))
            except (IndexError, TypeError, ValueError) as exc:
                raise ISSDataError(f"Malformed candle at offset {start}: {exc}") from exc
            if candle.timestamp in seen:
                raise ISSDataError(f"Duplicate candle timestamp returned by ISS: {candle.timestamp}")
            seen.add(candle.timestamp)
            result.append(candle)
        if not rows:
            break
        start += len(rows)
    if not result:
        raise ISSDataError(f"No candles returned for {ticker} {interval}m")
    return validate_candles(result)


def fetch_history_records(
    ticker: str, date_from: str, date_till: str, board: str = "TQBR",
    timeout: int = 20, retries: int = 3, getter=_get_json,
) -> list[HistoryRecord]:
    """Fetch public per-security daily history, including zero-trade rows.

    Rows absent from this endpoint are deliberately not interpreted as holidays,
    suspensions, pre-listing dates, or missing sessions.
    """
    ticker = ticker.strip().upper()
    board = board.strip().upper()
    start_date = date.fromisoformat(date_from)
    end_date = date.fromisoformat(date_till)
    if not ticker or not board:
        raise ValueError("ticker and board are required")
    if start_date > end_date:
        raise ValueError("date_from must be on or before date_till")

    start = 0
    result: list[HistoryRecord] = []
    seen: set[date] = set()
    while True:
        path = (
            f"{ISS_BASE}/history/engines/stock/markets/shares/boards/{quote(board)}/"
            f"securities/{quote(ticker)}.json"
        )
        query = urlencode({
            "from": date_from, "till": date_till, "start": start,
            "iss.meta": "off",
        })
        payload = getter(f"{path}?{query}", timeout=timeout, retries=retries)
        block = payload.get("history")
        if not isinstance(block, dict) or not isinstance(block.get("columns"), list) or not isinstance(block.get("data"), list):
            raise ISSDataError("MOEX ISS response lacks a valid history block")
        columns = block["columns"]
        required = {"TRADEDATE", "SECID", "BOARDID", "NUMTRADES"}
        if not required.issubset(columns):
            raise ISSDataError(f"MOEX ISS history columns missing: {sorted(required - set(columns))}")
        idx = {name: columns.index(name) for name in required}
        rows = block["data"]
        for row in rows:
            try:
                row_ticker = str(row[idx["SECID"]]).upper()
                row_board = str(row[idx["BOARDID"]]).upper()
                trade_date = date.fromisoformat(str(row[idx["TRADEDATE"]]))
                raw_count = row[idx["NUMTRADES"]]
                if row_ticker != ticker or row_board != board:
                    raise ISSDataError("MOEX ISS history returned a different security or board")
                if trade_date < start_date or trade_date > end_date:
                    raise ISSDataError(f"MOEX ISS history date outside requested range: {trade_date}")
                if raw_count is None:
                    num_trades = None
                else:
                    numeric_count = float(raw_count)
                    if not math.isfinite(numeric_count) or numeric_count < 0 or not numeric_count.is_integer():
                        raise ValueError("NUMTRADES must be a non-negative integer or null")
                    num_trades = int(numeric_count)
            except (IndexError, TypeError, ValueError) as exc:
                if isinstance(exc, ISSDataError):
                    raise
                raise ISSDataError(f"Malformed history row at offset {start}: {exc}") from exc
            if trade_date in seen:
                raise ISSDataError(f"Duplicate TQBR history date returned by ISS: {trade_date}")
            seen.add(trade_date)
            result.append(HistoryRecord(trade_date, num_trades))
        if not rows:
            break
        start += len(rows)
    return result


def save_csv(candles: list[Candle], path: str | Path) -> None:
    rows = validate_candles(candles)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c in rows:
            writer.writerow([c.timestamp.isoformat(), c.open, c.high, c.low, c.close, c.volume])
