"""Read fully closed hourly candles from the public MOEX ISS shares endpoint.

MOEX timestamps are interpreted as Europe/Moscow when the ISS response omits
an offset. The caller must still persist the last processed candle timestamp.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

ISS_BASE = "https://iss.moex.com/iss/engines/stock/markets/shares/securities"
MOSCOW = ZoneInfo("Europe/Moscow")
TIMEOUT = 15


class CandleDataError(RuntimeError):
    pass


def _parse_iss_datetime(value):
    if not isinstance(value, str) or not value.strip():
        raise CandleDataError("MOEX candle has no begin timestamp")
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CandleDataError(f"Invalid MOEX candle timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MOSCOW)
    return parsed.astimezone(timezone.utc)


def _decimal_field(value, field, ticker):
    from decimal import Decimal, InvalidOperation
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CandleDataError(f"{ticker}: invalid candle {field}") from exc
    if not number.is_finite() or number <= 0:
        raise CandleDataError(f"{ticker}: invalid candle {field}")
    return number


def parse_closed_h1_rows(columns, rows, now=None):
    """Parse ISS column-oriented rows; discard incomplete and future candles."""
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise CandleDataError("Malformed MOEX ISS candles payload")
    index = {name: i for i, name in enumerate(columns)}
    required = ("begin", "open", "high", "low", "close")
    if any(name not in index for name in required):
        raise CandleDataError("MOEX ISS candles response misses required columns")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, list) or len(row) < len(columns):
            raise CandleDataError("Malformed MOEX ISS candle row")
        begin = _parse_iss_datetime(row[index["begin"]])
        end = begin + timedelta(hours=1)
        if end > current:
            continue
        stamp = begin.isoformat()
        if stamp in seen:
            continue
        candle = {"timestamp": stamp}
        for field in ("open", "high", "low", "close"):
            candle[field] = _decimal_field(row[index[field]], field, "MOEX")
        if candle["low"] > candle["high"]:
            raise CandleDataError("MOEX candle low exceeds high")
        if not (candle["low"] <= candle["open"] <= candle["high"]):
            raise CandleDataError("MOEX candle open is outside high/low")
        if not (candle["low"] <= candle["close"] <= candle["high"]):
            raise CandleDataError("MOEX candle close is outside high/low")
        seen.add(stamp)
        result.append(candle)
    return sorted(result, key=lambda item: item["timestamp"])


def fetch_closed_h1_candles(ticker, days=7, now=None, session=None):
    """Fetch recent H1 candles, returning only fully closed validated rows."""
    symbol = str(ticker).strip().upper()
    if not symbol or not symbol.replace("-", "").isalnum():
        raise ValueError("Invalid ticker")
    if not isinstance(days, int) or days < 1 or days > 30:
        raise ValueError("days must be between 1 and 30")
    current = now or datetime.now(MOSCOW)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current_msk = current.astimezone(MOSCOW)
    params = {
        "interval": 60,
        "from": (current_msk.date() - timedelta(days=days)).isoformat(),
        "till": current_msk.date().isoformat(),
        "start": 0,
        "iss.meta": "off",
    }
    client = session or requests
    response = client.get(
        f"{ISS_BASE}/{symbol}/candles.json",
        params=params,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise CandleDataError("MOEX ISS returned a non-object payload")
    block = payload.get("candles")
    if not isinstance(block, dict):
        raise CandleDataError("MOEX ISS response has no candles block")
    candles = parse_closed_h1_rows(
        block.get("columns"), block.get("data"), now=current
    )
    if not candles:
        raise CandleDataError(f"{symbol}: no fully closed H1 candles returned")
    return candles
