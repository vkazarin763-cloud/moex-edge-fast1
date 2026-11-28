"""Read-only Finam corporate-action event retrieval for research audits.

Finam's historical dividend date is the register closing date, not the
ex-dividend/last-buy date. Split execution dates are separately defined.
This module records vendor events but deliberately does not adjust prices:
fund-distribution completeness and an authoritative ex-date mapping must
be independently verified before total-return calculations are enabled.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Callable
from urllib.parse import urlencode

BASE = "https://api.finam.ru"
PAGE_SIZE = 100
MAX_PAGES = 20


def sanitize_error_detail(value: object) -> str:
    """Keep only short, non-sensitive diagnostic text from vendor errors."""
    text = str(value or "")
    text = re.sub(
        r"(?i)(authorization|bearer|token|secret|account[_-]?id)\s*[:=]\s*[^,\s\"}]+",
        r"\1=[redacted]",
        text,
    )
    text = re.sub(r"[^A-Za-z0-9 _.,:/-]", " ", text)
    return " ".join(text.split())[:120] or "NO_ERROR_DETAIL"


class FinamRequestError(RuntimeError):
    def __init__(self, code: str, detail: object = "") -> None:
        self.code = code[:40]
        self.detail = sanitize_error_detail(detail)
        super().__init__(self.code)


def _date_params(prefix: str, value: date) -> dict[str, str]:
    return {
        f"{prefix}.year": str(value.year),
        f"{prefix}.month": str(value.month),
        f"{prefix}.day": str(value.day),
    }


def _event_date(event: dict) -> date | None:
    raw = event.get("date") or event.get("exec_date")
    if not isinstance(raw, dict):
        return None
    try:
        return date(int(raw["year"]), int(raw["month"]), int(raw["day"]))
    except (KeyError, TypeError, ValueError):
        return None


def fetch_event_pages(
    symbol: str,
    endpoint: str,
    list_key: str,
    token: str,
    start_date: date,
    end_date: date,
    *,
    requester: Callable,
    page_size: int = PAGE_SIZE,
    max_pages: int = MAX_PAGES,
) -> dict:
    """Retry without date query parameters after HTTP 400; then filter locally."""
    if not symbol or "@" not in symbol:
        raise ValueError("symbol must include exchange MIC")
    if endpoint not in ("/v1/past-dividends", "/v1/splits/past", "/v1/bonds/past"):
        raise ValueError("unsupported corporate-action endpoint")
    if start_date >= end_date:
        raise ValueError("start_date must precede end_date")
    if not 1 <= page_size <= 500 or not 1 <= max_pages <= 20:
        raise ValueError("invalid pagination limits")

    events = []
    offset = 0
    pages = 0
    date_filter_mode = "vendor"
    try:
        while pages < max_pages:
            params = {
                "symbol": symbol,
                "sort_direction": "asc",
                "limit": str(page_size),
                "offset": str(offset),
                **(_date_params("date_from", start_date) if date_filter_mode == "vendor" else {}),
                **(_date_params("date_to", end_date) if date_filter_mode == "vendor" else {}),
            }
            query = urlencode(params, safe=".")
            try:
                payload = requester(f"{BASE}{endpoint}?{query}", token)
            except FinamRequestError as exc:
                if exc.code != "HTTP_400" or date_filter_mode != "vendor":
                    raise
                date_filter_mode = "local_fallback"
                params = {
                    "symbol": symbol,
                    "sort_direction": "asc",
                    "limit": str(page_size),
                    "offset": str(offset),
                }
                payload = requester(f"{BASE}{endpoint}?{urlencode(params)}", token)
            if not isinstance(payload, dict) or not isinstance(payload.get(list_key), list):
                return {"status": "INVALID_RESPONSE", "events": [], "pages": pages, "date_filter_mode": date_filter_mode}
            page = payload[list_key]
            events.extend(page)
            pages += 1
            pagination = payload.get("pagination") or {}
            has_next = pagination.get("has_next")
            if has_next is False or not page:
                break
            if has_next is None and len(page) < page_size:
                break
            offset += len(page)
        if date_filter_mode == "local_fallback":
            events = [
                event for event in events
                if _event_date(event) is None or start_date <= _event_date(event) <= end_date
            ]
        return {
            "status": "OK" if pages < max_pages else "PAGE_LIMIT_REACHED",
            "events": events,
            "pages": pages,
            "date_filter_mode": date_filter_mode,
        }
    except FinamRequestError as exc:
        return {
            "status": "UNAVAILABLE", "error_code": exc.code,
            "error_detail": exc.detail, "events": [], "pages": pages,
            "date_filter_mode": date_filter_mode,
        }
    except Exception as exc:
        code = str(exc).split(":", 1)[0][:40] or "REQUEST_FAILED"
        return {"status": "UNAVAILABLE", "error_code": code, "events": [], "pages": pages, "date_filter_mode": date_filter_mode}


def fetch_instrument_corporate_actions(
    symbol: str,
    asset_class: str,
    token: str,
    start_date: date,
    end_date: date,
    *,
    requester: Callable,
) -> dict:
    """Retrieve historical dividends/distributions and equity splits for audit."""
    dividends = fetch_event_pages(
        symbol, "/v1/past-dividends", "dividends", token,
        start_date, end_date, requester=requester,
    )
    result = {"dividends": dividends, "splits": {"status": "NOT_APPLICABLE", "events": [], "pages": 0}}
    if asset_class == "equity":
        result["splits"] = fetch_event_pages(
            symbol, "/v1/splits/past", "splits", token,
            start_date, end_date, requester=requester,
        )
    result["adjustment_status"] = "NOT_ADJUSTED_DIVIDEND_DATE_IS_RECORD_DATE_AND_DISTRIBUTION_COVERAGE_UNVERIFIED"
    return result
