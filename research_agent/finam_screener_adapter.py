"""Read-only Finam AI Screener normalization for the frozen MOEX EDGE universe.

This adapter consumes structured responses from the authenticated interactive
Finam MCP tools. It does not connect to Finam, store credentials, access
accounts, fetch bars, or submit orders. Historical candle access remains in
research_agent.finam_market_data.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Iterable

UNIVERSE_VERSION = "v1-frozen-2026-11-19"
MARKET_ID = 2
ASSET_CLASS = "stock"
BATCH_SIZE = 10
METRICS = (
    "quote_last",
    "market_capitalization",
    "pe_ratio",
    "dividend_yield_12m",
)

# Verified by read-only Finam search_securities calls and screen_securities(ids=...).
FINAM_IDS = {
    "AFKS": 19715, "AFLT": 29, "ALRS": 81820, "BSPB": 20066,
    "CBOM": 420694, "CHMF": 16136, "CNRU": 5553030, "DOMRF": 6014007,
    "ENPG": 929597, "FLOT": 2101210, "GAZP": 16842, "GMKN": 795,
    "HEAD": 5287020, "IRAO": 20516, "LKOH": 8, "MAGN": 16782,
    "MDMG": 2152359, "MOEX": 152798, "MTSS": 15523, "NLMK": 17046,
    "NVTK": 17370, "OZON": 2179435, "PHOR": 81114, "PLZL": 17123,
    "POSI": 2907747, "RAGR": 5565687, "RENI": 2819863, "ROSN": 17273,
    "RTKM": 7, "RUAL": 414279, "SBER": 3, "SBERP": 23,
    "SNGS": 4, "SNGSP": 13, "SVCB": 4684694, "T": 5428482,
    "TATN": 825, "TATNP": 826, "TRNFP": 1012, "UGLD": 4638507,
    "VKCO": 2901666, "VTBR": 19043, "X5": 5442339, "YDEX": 5239179,
}
TICKERS = tuple(FINAM_IDS)
ID_TO_TICKER = {security_id: ticker for ticker, security_id in FINAM_IDS.items()}


class FinamScreenerDataError(ValueError):
    """Raised when a Finam screener response violates the read-only data contract."""


def _utc_iso(value: datetime | str) -> str:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise FinamScreenerDataError("retrieved_at must be an ISO timestamp or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FinamScreenerDataError("retrieved_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_screener_requests(batch_size: int = BATCH_SIZE) -> list[dict[str, Any]]:
    """Build deterministic read-only MCP arguments for the frozen 44-symbol set."""
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 10:
        raise FinamScreenerDataError("batch_size must be an integer from 1 through 10")
    ids = list(FINAM_IDS.values())
    requests = []
    for offset in range(0, len(ids), batch_size):
        requests.append({
            "asset_class": ASSET_CLASS,
            "market": MARKET_ID,
            "ids": ids[offset:offset + batch_size],
            "sort": "market_capitalization",
            "ordering": "desc",
            "limit": 10,
            "metrics": list(METRICS),
        })
    return requests


def _number(value: Any, field: str, *, nullable: bool = True) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool):
        raise FinamScreenerDataError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise FinamScreenerDataError(f"{field} must be numeric") from None
    if not math.isfinite(result):
        raise FinamScreenerDataError(f"{field} must be finite")
    return result


def _extract_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        raise FinamScreenerDataError("each screener response must be an object")
    payload = response
    while isinstance(payload.get("result"), dict):
        payload = payload["result"]
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise FinamScreenerDataError("screener response is missing data[]")
    return rows


def normalize_screener_responses(
    responses: Iterable[dict[str, Any]],
    *,
    retrieved_at: datetime | str,
    expected_tickers: Iterable[str] = TICKERS,
) -> dict[str, Any]:
    """Validate and normalize raw screen_securities JSON responses.

    dividend_yield_12m is preserved as the provider's fractional value and also
    exposed as percentage points (fraction * 100). No quote timestamp is inferred
    from retrieval time or chart-bar timestamps.
    """
    retrieved = _utc_iso(retrieved_at)
    expected = tuple(expected_tickers)
    if len(expected) != len(set(expected)) or any(t not in FINAM_IDS for t in expected):
        raise FinamScreenerDataError("expected_tickers must be unique members of the frozen universe")
    expected_ids = {FINAM_IDS[t] for t in expected}
    found: dict[str, dict[str, Any]] = {}

    for response in responses:
        for row in _extract_rows(response):
            if not isinstance(row, dict):
                raise FinamScreenerDataError("screener data rows must be objects")
            asset = row.get("asset")
            if not isinstance(asset, dict):
                raise FinamScreenerDataError("screener row is missing asset metadata")
            security_id = asset.get("security_id")
            if isinstance(security_id, bool) or not isinstance(security_id, int):
                raise FinamScreenerDataError("asset.security_id must be an integer")
            if security_id not in ID_TO_TICKER:
                raise FinamScreenerDataError(f"unexpected Finam security_id: {security_id}")
            ticker = ID_TO_TICKER[security_id]
            if security_id not in expected_ids:
                raise FinamScreenerDataError(f"unexpected ticker outside requested universe: {ticker}")
            if ticker in found:
                raise FinamScreenerDataError(f"duplicate screener row: {ticker}")
            if asset.get("ticker") != ticker:
                raise FinamScreenerDataError(f"ticker/ID mismatch for security_id {security_id}")
            if asset.get("market") != MARKET_ID:
                raise FinamScreenerDataError(f"unexpected market for {ticker}")

            price = _number(row.get("quote_last"), "quote_last")
            cap = _number(row.get("market_capitalization"), "market_capitalization")
            pe = _number(row.get("pe_ratio"), "pe_ratio")
            yield_fraction = _number(row.get("dividend_yield_12m"), "dividend_yield_12m")
            if price is not None and price <= 0:
                raise FinamScreenerDataError(f"quote_last must be positive for {ticker}")
            if cap is not None and cap < 0:
                raise FinamScreenerDataError(f"market_capitalization cannot be negative for {ticker}")
            if yield_fraction is not None and yield_fraction < 0:
                raise FinamScreenerDataError(f"dividend_yield_12m cannot be negative for {ticker}")

            found[ticker] = {
                "ticker": ticker,
                "finam_security_id": security_id,
                "quote_last": price,
                "market_capitalization": cap,
                "pe_ratio": pe,
                "dividend_yield_12m_fraction": yield_fraction,
                "dividend_yield_12m_percent": (
                    yield_fraction * 100.0 if yield_fraction is not None else None
                ),
                "quote_timestamp_utc": None,
                "quote_freshness": "UNKNOWN_NO_PROVIDER_QUOTE_TIMESTAMP",
            }

    missing = [ticker for ticker in expected if ticker not in found]
    if missing:
        raise FinamScreenerDataError(f"incomplete universe; missing tickers: {','.join(missing)}")

    return {
        "schema_version": 1,
        "provider": "Finam AI Screener MCP",
        "universe_version": UNIVERSE_VERSION,
        "market": MARKET_ID,
        "asset_class": ASSET_CLASS,
        "retrieved_at_utc": retrieved,
        "quote_timestamp_available": False,
        "quote_freshness": "UNKNOWN",
        "metrics": list(METRICS),
        "expected_count": len(expected),
        "received_count": len(found),
        "missing_tickers": [],
        "records": [found[ticker] for ticker in expected],
    }
