"""Read-only Finam Trade API market-data client.

This module only authenticates a market-data session and fetches historical bars.
It has no account, order, portfolio, or execution methods.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .core import Candle, validate_candles

FINAM_BASE = "https://api.finam.ru"
TIMEFRAME_MAX_DAYS = {
    "TIME_FRAME_M1": 7,
    "TIME_FRAME_M5": 30,
    "TIME_FRAME_M15": 30,
    "TIME_FRAME_M30": 30,
    "TIME_FRAME_H1": 30,
    "TIME_FRAME_H2": 30,
    "TIME_FRAME_H4": 30,
    "TIME_FRAME_H8": 30,
    "TIME_FRAME_D": 365,
    "TIME_FRAME_W": 365 * 5,
    "TIME_FRAME_MN": 365 * 5,
    "TIME_FRAME_QR": 365 * 5,
}


class FinamAPIError(RuntimeError):
    """Raised for Finam authentication, transport, or payload errors."""


@dataclass(frozen=True)
class FinamBar:
    """A Finam bar with its source timestamp and snapshot metadata."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_data_snapshot: bool | None

    def as_candle(self) -> Candle:
        return Candle(self.timestamp, self.open, self.high, self.low,
                      self.close, self.volume)


def _request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict | None = None,
    timeout: int = 20,
) -> dict:
    """Make one JSON request without logging credentials or response bodies."""
    request_headers = {"Accept": "application/json", **(headers or {})}
    data = None
    if body is not None:
        request_headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise FinamAPIError(f"Finam API returned HTTP {response.status}")
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise FinamAPIError(f"Finam API returned HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise FinamAPIError("Finam API transport request failed") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise FinamAPIError("Finam API returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise FinamAPIError("Finam API response must be a JSON object")
    return payload


def _parse_decimal(value: object, field: str) -> float:
    if isinstance(value, dict):
        value = value.get("value")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise FinamAPIError(f"Finam bar has invalid {field}") from None
    if not math.isfinite(parsed):
        raise FinamAPIError(f"Finam bar has non-finite {field}")
    return parsed


def _parse_timestamp(value: object) -> datetime:
    try:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, dict) and "seconds" in value:
            parsed = datetime.fromtimestamp(
                int(value["seconds"]) + int(value.get("nanos", 0)) / 1_000_000_000,
                tz=timezone.utc,
            )
        else:
            raise ValueError("unsupported timestamp representation")
    except (TypeError, ValueError, OverflowError, OSError):
        raise FinamAPIError("Finam bar has invalid timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FinamAPIError("Finam bar timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def create_access_token(
    api_token: str,
    source_app_id: str | None = None,
    *,
    requester: Callable = _request_json,
    timeout: int = 20,
) -> str:
    """Exchange a Finam API token for a short-lived JWT access token."""
    if not isinstance(api_token, str) or not api_token.strip():
        raise ValueError("A non-empty Finam API token is required")
    body = {"secret": api_token.strip()}
    if source_app_id and source_app_id.strip():
        body["source_app_id"] = source_app_id.strip()
    payload = requester(
        f"{FINAM_BASE}/v1/sessions",
        method="POST",
        body=body,
        timeout=timeout,
    )
    token = payload.get("token")
    if not isinstance(token, str) or not token.strip():
        raise FinamAPIError("Finam authentication response did not contain a token")
    return token.strip()


class FinamMarketDataClient:
    """Small read-only client for historical aggregated candles."""

    def __init__(
        self,
        access_token: str,
        *,
        requester: Callable = _request_json,
        timeout: int = 20,
    ) -> None:
        if not isinstance(access_token, str) or not access_token.strip():
            raise ValueError("A non-empty Finam access token is required")
        self._access_token = access_token.strip()
        self._requester = requester
        self._timeout = timeout

    @classmethod
    def from_api_token(
        cls,
        api_token: str,
        source_app_id: str | None = None,
        *,
        requester: Callable = _request_json,
        timeout: int = 20,
    ) -> "FinamMarketDataClient":
        token = create_access_token(
            api_token, source_app_id, requester=requester, timeout=timeout
        )
        return cls(token, requester=requester, timeout=timeout)

    def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[FinamBar]:
        """Fetch bars for [start_time, end_time); enforce Finam history limits.

        Finam documents maximum lookback windows per timeframe. The caller must
        pass an exchange-qualified symbol such as SBER@MISX and aware datetimes.
        """
        symbol = symbol.strip().upper() if isinstance(symbol, str) else ""
        if not symbol or "@" not in symbol:
            raise ValueError("symbol must include an exchange MIC, e.g. SBER@MISX")
        if timeframe not in TIMEFRAME_MAX_DAYS:
            raise ValueError(f"Unsupported Finam timeframe: {timeframe}")
        if (not isinstance(start_time, datetime) or not isinstance(end_time, datetime)
                or start_time.tzinfo is None or end_time.tzinfo is None
                or start_time.utcoffset() is None or end_time.utcoffset() is None):
            raise ValueError("start_time and end_time must be timezone-aware")
        start_utc = start_time.astimezone(timezone.utc)
        end_utc = end_time.astimezone(timezone.utc)
        if start_utc >= end_utc:
            raise ValueError("start_time must be earlier than end_time")
        max_window = timedelta(days=TIMEFRAME_MAX_DAYS[timeframe])
        if end_utc - start_utc > max_window:
            raise ValueError(
                f"{timeframe} history window exceeds documented "
                f"{TIMEFRAME_MAX_DAYS[timeframe]}-day limit"
            )

        query = urlencode({
            "timeframe": timeframe,
            "interval.start_time": start_utc.isoformat().replace("+00:00", "Z"),
            "interval.end_time": end_utc.isoformat().replace("+00:00", "Z"),
        })
        url = f"{FINAM_BASE}/v1/instruments/{quote(symbol, safe='@')}/bars?{query}"
        payload = self._requester(
            url,
            headers={"Authorization": f"Bearer {self._access_token}"},
            timeout=self._timeout,
        )
        returned_symbol = payload.get("symbol")
        if not isinstance(returned_symbol, str) or returned_symbol.strip().upper() != symbol:
            raise FinamAPIError("Finam response symbol does not match the requested instrument")
        raw_bars = payload.get("bars")
        if not isinstance(raw_bars, list):
            raise FinamAPIError("Finam response lacks a valid bars array")

        result: list[FinamBar] = []
        for index, raw in enumerate(raw_bars):
            if not isinstance(raw, dict):
                raise FinamAPIError(f"Finam bar {index} is not an object")
            timestamp = _parse_timestamp(raw.get("timestamp"))
            snapshot_value = raw.get("is_data_snapshot")
            if snapshot_value is not None and not isinstance(snapshot_value, bool):
                raise FinamAPIError(f"Finam bar {index} has invalid is_data_snapshot")
            bar = FinamBar(
                timestamp=timestamp,
                open=_parse_decimal(raw.get("open"), "open"),
                high=_parse_decimal(raw.get("high"), "high"),
                low=_parse_decimal(raw.get("low"), "low"),
                close=_parse_decimal(raw.get("close"), "close"),
                volume=_parse_decimal(raw.get("volume"), "volume"),
                is_data_snapshot=snapshot_value,
            )
            result.append(bar)

        if result:
            try:
                validate_candles([bar.as_candle() for bar in result])
            except ValueError as exc:
                raise FinamAPIError(f"Invalid Finam OHLCV series: {exc}") from None
            # Finam D1 timestamps are session-start stamps (typically 05:00 UTC),
            # while a strict rolling 365-day request can start later on that same
            # UTC date. Treat the lower D1 boundary as date-inclusive, but keep
            # the exclusive upper timestamp boundary and the exact 365-day limit.
            if timeframe == "TIME_FRAME_D":
                outside = next((
                    bar for bar in result
                    if bar.timestamp.date() < start_utc.date() or bar.timestamp >= end_utc
                ), None)
            else:
                outside = next((
                    bar for bar in result
                    if bar.timestamp < start_utc or bar.timestamp >= end_utc
                ), None)
            if outside is not None:
                raise FinamAPIError(
                    "Finam returned a bar outside the requested interval: "
                    f"timestamp={outside.timestamp.isoformat()}, "
                    f"requested=[{start_utc.isoformat()}, {end_utc.isoformat()})"
                )
        return result
