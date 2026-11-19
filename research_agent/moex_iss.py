"""Read-only MOEX ISS candle ingestion for the isolated research agent.

No authentication, broker access, or order submission is used.
"""
from __future__ import annotations

import csv
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .core import Candle, validate_candles

ISS_BASE = "https://iss.moex.com/iss"
PAGE_SIZE = 500


class ISSDataError(RuntimeError):
    """Raised when MOEX ISS returns incomplete or malformed candle data."""


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
                  page_size: int = PAGE_SIZE, getter=_get_json) -> list[Candle]:
    """Fetch all available candles for one symbol/timeframe; gaps are preserved."""
    ticker = ticker.strip().upper()
    board = board.strip().upper()
    if not ticker or not board:
        raise ValueError("ticker and board are required")
    if interval not in (1, 10, hourly:=60, 24, 7, 31, 4):
        raise ValueError("Unsupported MOEX candle interval")
    if page_size < 1:
        raise ValueError("page_size must be positive")
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
        if len(rows) < page_size:
            break
        start += len(rows)
    if not result:
        raise ISSDataError(f"No candles returned for {ticker} {interval}m")
    return validate_candles(result)


def save_csv(candles: list[Candle], path: str | Path) -> None:
    rows = validate_candles(candles)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c in rows:
            writer.writerow([c.timestamp.isoformat(), c.open, c.high, c.low, c.close, c.volume])
