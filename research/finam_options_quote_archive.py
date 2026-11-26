"""Bounded read-only collector for current Finam option quotes and order books.

This archives forward observations; it does not reconstruct historical quotes.
Only session authentication and market-data GET requests are used.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

import requests

BASE = "https://api.finam.ru"
DEFAULT_SYMBOLS = ("GZ100CX6@RTSX", "SR290CX6@RTSX")
TIMEOUT = 15


class CollectorError(RuntimeError):
    pass


def val(x):
    return x.get("value") if isinstance(x, dict) else x


def dec(x):
    try:
        n = Decimal(str(val(x)))
        return n if n.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


class Finam:
    def __init__(self, secret: str):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "moex-options-forward-quote-archive/1.0"
        try:
            r = self.s.post(f"{BASE}/v1/sessions", json={"secret": secret}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise CollectorError(f"auth_network_{type(exc).__name__}") from None
        if r.status_code != 200:
            raise CollectorError(f"auth_http_{r.status_code}")
        token = r.json().get("token")
        if not isinstance(token, str) or not token:
            raise CollectorError("auth_token_missing")
        self.s.headers["Authorization"] = f"Bearer {token}"

    def get(self, path):
        try:
            r = self.s.get(f"{BASE}{path}", timeout=TIMEOUT)
        except requests.RequestException as exc:
            return None, f"network_{type(exc).__name__}"
        if r.status_code != 200:
            return None, f"http_{r.status_code}"
        try:
            return r.json(), None
        except ValueError:
            return None, "invalid_json"


def snapshot(api: Finam, symbol: str) -> dict:
    encoded = quote(symbol, safe="")
    quote_data, quote_error = api.get(f"/v1/instruments/{encoded}/quotes/latest")
    book_data, book_error = api.get(f"/v1/instruments/{encoded}/orderbook")
    q = quote_data.get("quote", {}) if isinstance(quote_data, dict) else {}
    book = book_data.get("orderbook", {}) if isinstance(book_data, dict) else {}
    rows = book.get("rows", []) if isinstance(book, dict) else []
    bids, asks = [], []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        p = dec(row.get("price"))
        b = dec(row.get("buy_size")) or Decimal(0)
        a = dec(row.get("sell_size")) or Decimal(0)
        if p is None or p <= 0:
            continue
        if b > 0:
            bids.append((p, b))
        if a > 0:
            asks.append((p, a))
    best_bid = max((x[0] for x in bids), default=None)
    best_ask = min((x[0] for x in asks), default=None)
    mid = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None
    spread = ((best_ask - best_bid) / mid * 100) if mid and mid > 0 else None
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "quote_error": quote_error,
        "book_error": book_error,
        "quote": {
            "timestamp": q.get("timestamp"),
            "bid": val(q.get("bid")),
            "ask": val(q.get("ask")),
            "last": val(q.get("last")),
            "bid_size": val(q.get("bid_size")),
            "ask_size": val(q.get("ask_size")),
            "open_interest": val(q.get("open_interest")),
        } if isinstance(q, dict) else None,
        "orderbook": {
            "rows_received": len(rows) if isinstance(rows, list) else 0,
            "best_bid": str(best_bid) if best_bid is not None else None,
            "best_bid_size": str(sum((s for p, s in bids if p == best_bid), Decimal(0))) if best_bid is not None else None,
            "best_ask": str(best_ask) if best_ask is not None else None,
            "best_ask_size": str(sum((s for p, s in asks if p == best_ask), Decimal(0))) if best_ask is not None else None,
            "spread_pct": round(float(spread), 5) if spread is not None else None,
            "raw_levels": rows if isinstance(rows, list) else [],
        } if isinstance(book, dict) else None,
    }


def main():
    secret = os.environ.get("FINAM_API_SECRET", "")
    if not secret:
        raise CollectorError("FINAM_API_SECRET_missing")
    duration = int(os.environ.get("CAPTURE_MINUTES", "60"))
    interval = int(os.environ.get("POLL_SECONDS", "15"))
    if not 1 <= duration <= 240:
        raise CollectorError("CAPTURE_MINUTES_must_be_1_to_240")
    if not 10 <= interval <= 60:
        raise CollectorError("POLL_SECONDS_must_be_10_to_60")
    symbols = tuple(x.strip() for x in os.environ.get("OPTION_SYMBOLS", ",".join(DEFAULT_SYMBOLS)).split(",") if x.strip())
    if not symbols or len(symbols) > 4:
        raise CollectorError("OPTION_SYMBOLS_must_contain_1_to_4_symbols")

    api = Finam(secret)
    output = Path("finam-options-quote-archive.jsonl")
    deadline = time.monotonic() + duration * 60
    count = 0
    errors = 0
    with output.open("w", encoding="utf-8") as f:
        f.write(json.dumps({
            "record_type": "metadata",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "duration_minutes": duration,
            "poll_seconds": interval,
            "symbols": symbols,
            "safety": {
                "market_data_get_only": True,
                "account_endpoints_called": False,
                "order_or_cancel_endpoints_called": False,
                "secret_or_token_written": False,
            },
            "limitations": [
                "This is a forward archive of snapshots collected while the workflow runs.",
                "Snapshots are not proof of fillability, queue priority, or available size beyond displayed levels.",
                "No orders are submitted; this workflow cannot execute trades.",
            ],
        }, ensure_ascii=False) + "\n")
        f.flush()
        while time.monotonic() < deadline:
            cycle_start = time.monotonic()
            for symbol in symbols:
                record = snapshot(api, symbol)
                count += 1
                errors += bool(record["quote_error"] or record["book_error"])
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            remaining = interval - (time.monotonic() - cycle_start)
            if remaining > 0 and time.monotonic() + remaining < deadline:
                time.sleep(remaining)
    print(json.dumps({
        "status": "completed",
        "snapshot_records": count,
        "records_with_endpoint_errors": errors,
        "symbols": symbols,
        "artifact": str(output),
    }, ensure_ascii=False))
    if count == 0:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except (CollectorError, ValueError) as exc:
        print(f"FINAM OPTIONS QUOTE ARCHIVE: FAILED ({exc})")
        sys.exit(1)
