"Read-only Finam corporate-action event retrieval for research audits.

Finam's historical dividend date is the register closing date, not the
ex-dividend/last-buy date. Split execution dates are separately defined.
This module records vendor events but deliberately does not adjust prices:
fund-distribution completeness and an authoritative ex-date mapping must
be independently verified before total-return calculations are enabled.
"""
from __future__ import annotations

from datetime import date
from typing import Callable
from urllib.parse import urlencode

BASE = "https://api.finam.ru"
PAGE_SIZE = 100
MAX_PAGES = 20


def _date_params(prefix: str, value: date) -> dict[str, str]:
    return {
        f"{prefix}.year": str(value.year),
        f"{prefix}.month": str(value.month),
        f"{prefix}.day": str(value.day),
    }


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
    """Fetch a paginated read-only event list; never returns auth/error bodies."""
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
    try:
        while pages < max_pages:
            params = {
                "symbol": symbol,
                "sort_direction": "asc",
                "limit": str(page_size),
                "offset": str(offset),
                **_date_params("date_from", start_date),
                **_date_params("date_to", end_date),
            }
            # Finam's documented query names contain literal dots (date_from.year).
            # Preserve them: some API gateways do not normalize %2E in parameter keys.
            query = urlencode(params, safe=".")
            payload = requester(f"{BASE}{endpoint}?{query}", token)
            if not isinstance(payload, dict) or not isinstance(payload.get(list_key), list):
                return {"status": "INVALID_RESPONSE", "events": [], "pages": pages}
            page = payload[list_key]
            events.extend(page)
            pages += 1
            pagination = payload.get("pagination") or {}
            has_next = pagination.get("has_next")
            if has_next is False or not page:
                return {"status": "OK", "events": events, "pages": pages}
            if has_next is None and len(page) < page_size:
                return {"status": "OK", "events": events, "pages": pages}
            offset += len(page)
        return {"status": "PAGE_LIMIT_REACHED", "events": events, "pages": pages}
    except Exception as exc:
        code = str(exc).split(":", 1)[0][:40] or "REQUEST_FAILED"
        return {"status": "UNAVAILABLE", "error_code": code, "events": [], "pages": pages}


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
