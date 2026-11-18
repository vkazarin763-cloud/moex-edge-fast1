"""Small, deterministic helpers for H1 percentage-based position exits.

This module deliberately contains no broker/API calls. The executor can use
these functions after it has obtained a verified, fully closed H1 candle.
"""
from decimal import Decimal, InvalidOperation


STOP_LOSS_PCT = Decimal("3.0")
TAKE_PROFIT_PCT = Decimal("5.0")


def _price(value, name):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {name}: {value!r}") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"Invalid {name}: {value!r}")
    return result


def calculate_exit_levels(entry_price, direction):
    """Return (stop_loss, take_profit), both measured from actual fill price."""
    entry = _price(entry_price, "entry_price")
    side = str(direction).strip().upper()
    stop = STOP_LOSS_PCT / Decimal("100")
    target = TAKE_PROFIT_PCT / Decimal("100")
    if side == "LONG":
        return entry * (1 - stop), entry * (1 + target)
    if side == "SHORT":
        return entry * (1 + stop), entry * (1 - target)
    raise ValueError(f"Invalid direction: {direction!r}")


def evaluate_closed_h1_candle(entry_price, direction, candle):
    """Return 'STOP_LOSS', 'TAKE_PROFIT', or None for one completed H1 candle.

    If both levels are inside the same candle, stop-loss wins conservatively.
    The caller is responsible for proving that the candle is fully closed.
    """
    if not isinstance(candle, dict):
        raise ValueError("Candle must be a dict")
    high = _price(candle.get("high"), "high")
    low = _price(candle.get("low"), "low")
    open_price = _price(candle.get("open"), "open")
    close = _price(candle.get("close"), "close")
    if low > high or not (low <= open_price <= high) or not (low <= close <= high):
        raise ValueError("Invalid OHLC candle")

    stop, target = calculate_exit_levels(entry_price, direction)
    side = str(direction).strip().upper()
    if side == "LONG":
        if low <= stop:
            return "STOP_LOSS"
        if high >= target:
            return "TAKE_PROFIT"
    else:
        if high >= stop:
            return "STOP_LOSS"
        if low <= target:
            return "TAKE_PROFIT"
    return None
