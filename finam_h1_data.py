"""Validated closed H1 candles from Finam Trade API.

Finam documents TIME_FRAME_H1 with a 30-day history window. Snapshot bars
are excluded; a candle is eligible only after its one-hour interval ends.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation


class FinamCandleDataError(RuntimeError):
    pass


def _timestamp(value):
    if not isinstance(value, str) or not value.strip():
        raise FinamCandleDataError("Finam bar has no timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinamCandleDataError("Finam bar timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise FinamCandleDataError("Finam bar timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _decimal(value, field):
    if isinstance(value, dict):
        value = value.get("value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FinamCandleDataError(f"Invalid Finam bar {field}") from exc
    if not result.is_finite() or result <= 0:
        raise FinamCandleDataError(f"Invalid Finam bar {field}")
    return result


def parse_closed_h1_bars(bars, now=None):
    """Return sorted, unique, validated closed H1 bars; omit snapshots."""
    if not isinstance(bars, list):
        raise FinamCandleDataError("Finam bars payload is not a list")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    result = {}
    for bar in bars:
        if not isinstance(bar, dict):
            raise FinamCandleDataError("Malformed Finam bar")
        snapshot = bar.get("is_data_snapshot", False)
        if not isinstance(snapshot, bool):
            raise FinamCandleDataError("Invalid Finam snapshot flag")
        if snapshot:
            continue
        stamp = _timestamp(bar.get("timestamp"))
        if stamp + timedelta(hours=1) > current:
            continue
        candle = {"timestamp": stamp.isoformat()}
        for field in ("open", "high", "low", "close"):
            candle[field] = _decimal(bar.get(field), field)
        if candle["low"] > candle["high"]:
            raise FinamCandleDataError("Finam candle low exceeds high")
        if not candle["low"] <= candle["open"] <= candle["high"]:
            raise FinamCandleDataError("Finam candle open outside high/low")
        if not candle["low"] <= candle["close"] <= candle["high"]:
            raise FinamCandleDataError("Finam candle close outside high/low")
        result[candle["timestamp"]] = candle
    return [result[key] for key in sorted(result)]


def fetch_closed_h1_candles(token, symbol, api_get, now=None, days=7):
    """Fetch H1 bars through the authenticated Finam API."""
    from urllib.parse import quote

    if not isinstance(symbol, str) or "@" not in symbol:
        raise ValueError("Finam symbol must be ticker@mic")
    if not isinstance(days, int) or days < 1 or days > 30:
        raise ValueError("days must be between 1 and 30")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    start = current - timedelta(days=days)
    payload = api_get(
        f"https://api.finam.ru/v1/instruments/{quote(symbol, safe='@')}/bars",
        token,
        params={
            "timeframe": "TIME_FRAME_H1",
            "interval.start_time": start.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "interval.end_time": current.isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("bars"), list):
        raise FinamCandleDataError("Finam response has no bars array")
    candles = parse_closed_h1_bars(payload["bars"], now=current)
    if not candles:
        raise FinamCandleDataError(f"{symbol}: no closed H1 bars returned")
    return candles
