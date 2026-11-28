#!/usr/bin/env python3
"""One-symbol, read-only Finam corporate-actions request diagnostic.

Prints HTTP status and sanitized vendor error text only. Never prints tokens,
authorization headers, full response bodies, or returned personal data.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_agent.finam_market_data import create_access_token

BASE = "https://api.finam.ru"
SYMBOL = "SBER@MISX"


def sanitize(value: object) -> str:
    text = str(value or "")
    text = re.sub(
        r"(?i)(authorization|bearer|token|secret|account[_-]?id)\s*[:=]\s*[^,\s\"}]+",
        r"\1=[redacted]",
        text,
    )
    text = re.sub(r"[^A-Za-z0-9 _.,:/-]", " ", text)
    return " ".join(text.split())[:180] or "NO_VENDOR_MESSAGE"


def error_message(raw: bytes) -> str:
    decoded = raw[:4096].decode("utf-8", "replace")
    try:
        payload = json.loads(decoded)
    except Exception:
        return sanitize(decoded)
    candidates = []

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {"message", "detail", "error", "description", "title", "reason"}:
                    if isinstance(child, (str, int, float)):
                        candidates.append(str(child))
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return sanitize(" | ".join(candidates[:3]))


def main() -> None:
    import os

    secret = os.environ.get("FINAM_API_SECRET", "").strip()
    if not secret:
        raise SystemExit("FINAM_API_SECRET_MISSING")
    token = create_access_token(secret)
    date_params = {
        "date_from.year": "2021", "date_from.month": "1", "date_from.day": "1",
        "date_to.year": "2026", "date_to.month": "11", "date_to.day": "28",
    }
    variants = [
        ("symbol_limit", {"symbol": SYMBOL, "limit": "100", "offset": "0"}),
        ("enum_asc", {"symbol": SYMBOL, "sort_direction": "ASC", "limit": "100", "offset": "0"}),
        ("enum_desc", {"symbol": SYMBOL, "sort_direction": "DESC", "limit": "100", "offset": "0"}),
        ("full_dates", {"symbol": SYMBOL, "sort_direction": "ASC", "limit": "100", "offset": "0", **date_params}),
    ]
    for endpoint, list_key in (("/v1/past-dividends", "dividends"), ("/v1/splits/past", "splits")):
        print(f"ENDPOINT {endpoint} SYMBOL {SYMBOL}")
        for label, params in variants:
            time.sleep(0.4)
            url = f"{BASE}{endpoint}?{urlencode(params, safe='.')}"
            request = Request(url, headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "moex-edge-readonly-diagnostic/1.0",
            })
            try:
                with urlopen(request, timeout=20) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    events = payload.get(list_key, [])
                    pagination = payload.get("pagination", {})
                    event_count = len(events) if isinstance(events, list) else "INVALID"
                    has_next = pagination.get("has_next") if isinstance(pagination, dict) else "UNKNOWN"
                    print(f"  {label}: HTTP {response.status}; keys={','.join(sorted(payload.keys()))}; events={event_count}; has_next={has_next}")
            except HTTPError as exc:
                print(f"  {label}: HTTP {exc.code}; {error_message(exc.read())}")
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                print(f"  {label}: TRANSPORT_OR_JSON_ERROR {sanitize(type(exc).__name__)}")
        print("")


if __name__ == "__main__":
    main()
