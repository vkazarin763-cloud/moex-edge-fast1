"""Isolated, deterministic research primitives for MOEX EDGE.

This module never imports or calls broker/execution code. All signals are evaluated
at a completed bar and entered at the next available bar's open.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    index: int
    direction: int  # +1 LONG, -1 SHORT
    strategy: str


@dataclass(frozen=True)
class Trade:
    strategy: str
    direction: int
    signal_time: datetime
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_price: float
    exit_price: Optional[float]
    net_return: Optional[float]
    status: str
    exit_reason: str


@dataclass(frozen=True)
class BacktestConfig:
    fee_per_side: float = 0.001
    slippage_per_side: float = 0.0005
    stop_pct: Optional[float] = 0.03
    target_pct: Optional[float] = 0.06
    max_bars: Optional[int] = 120


def load_csv(path: str | Path) -> list[Candle]:
    """Load timestamp,open,high,low,close,volume CSV; reject malformed data."""
    candles: list[Candle] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError(f"CSV must contain columns: {sorted(required)}")
        for line_no, row in enumerate(reader, start=2):
            try:
                ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
                vals = [float(row[k]) for k in ("open", "high", "low", "close", "volume")]
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError(f"Invalid CSV row {line_no}: {exc}") from exc
            candles.append(Candle(ts, *vals))
    validate_candles(candles)
    return candles


def validate_candles(candles: Iterable[Candle]) -> list[Candle]:
    rows = list(candles)
    if not rows:
        raise ValueError("No candles supplied")
    previous = None
    for i, c in enumerate(rows):
        values = (c.open, c.high, c.low, c.close, c.volume)
        if not all(math.isfinite(x) for x in values):
            raise ValueError(f"Non-finite OHLCV at row {i}")
        if min(c.open, c.high, c.low, c.close) <= 0 or c.volume < 0:
            raise ValueError(f"Non-positive price or negative volume at row {i}")
        if c.high < max(c.open, c.close, c.low) or c.low > min(c.open, c.close, c.high):
            raise ValueError(f"Invalid OHLC relationship at row {i}")
        if previous is not None and c.timestamp <= previous:
            raise ValueError(f"Timestamps must be strictly increasing; duplicate/out-of-order at row {i}")
        previous = c.timestamp
    return rows


def _ema(values: list[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1.0)
    out = []
    current = values[0]
    for value in values:
        current = alpha * value + (1.0 - alpha) * current
        out.append(current)
    return out


def _wilder_rsi(closes: list[float], period: int = 14) -> list[Optional[float]]:
    result: list[Optional[float]] = [None] * len(closes)
    if len(closes) <= period:
        return result
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(closes)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_gain == 0 and avg_loss == 0:
            result[i] = 50.0
        elif avg_loss == 0:
            result[i] = 100.0
        else:
            result[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return result


def _wilder_atr(rows: list[Candle], period: int = 14) -> list[Optional[float]]:
    tr = []
    for i, candle in enumerate(rows):
        if i == 0:
            tr.append(candle.high - candle.low)
        else:
            previous_close = rows[i - 1].close
            tr.append(max(candle.high - candle.low,
                          abs(candle.high - previous_close),
                          abs(candle.low - previous_close)))
    result: list[Optional[float]] = [None] * len(rows)
    if len(rows) < period:
        return result
    current = sum(tr[:period]) / period
    result[period - 1] = current
    for i in range(period, len(rows)):
        current = (current * (period - 1) + tr[i]) / period
        result[i] = current
    return result


def generate_signals(candles: list[Candle]) -> list[Signal]:
    """Pre-registered candidate set; fixed parameters, no fitting or look-ahead."""
    rows = validate_candles(candles)
    closes = [c.close for c in rows]
    ema12, ema20, ema26, ema50 = (
        _ema(closes, 12), _ema(closes, 20), _ema(closes, 26), _ema(closes, 50)
    )
    macd = [fast - slow for fast, slow in zip(ema12, ema26)]
    macd_signal = _ema(macd, 9)
    rsi14 = _wilder_rsi(closes, 14)
    atr14 = _wilder_atr(rows, 14)
    keltner_upper = [
        ema20[i] + 2.0 * atr14[i] if atr14[i] is not None else None
        for i in range(len(rows))
    ]
    keltner_lower = [
        ema20[i] - 2.0 * atr14[i] if atr14[i] is not None else None
        for i in range(len(rows))
    ]
    signals: list[Signal] = []
    for i in range(55, len(rows) - 1):
        # Donchian levels exclude the current completed candle.
        prior_high = max(c.high for c in rows[i - 20:i])
        prior_low = min(c.low for c in rows[i - 20:i])
        if rows[i].close > prior_high:
            signals.append(Signal(i, 1, "Donchian20"))
        elif rows[i].close < prior_low:
            signals.append(Signal(i, -1, "Donchian20"))

        # EMA trend change, confirmed only at the current completed close.
        if ema20[i] > ema50[i] and ema20[i - 1] <= ema50[i - 1]:
            signals.append(Signal(i, 1, "EMA20x50"))
        elif ema20[i] < ema50[i] and ema20[i - 1] >= ema50[i - 1]:
            signals.append(Signal(i, -1, "EMA20x50"))

        # RSI momentum crossing with a slow trend direction filter.
        if rsi14[i] is not None and rsi14[i - 1] is not None:
            if ema20[i] > ema50[i] and rsi14[i] > 50 and rsi14[i - 1] <= 50:
                signals.append(Signal(i, 1, "RSI14Trend50"))
            elif ema20[i] < ema50[i] and rsi14[i] < 50 and rsi14[i - 1] >= 50:
                signals.append(Signal(i, -1, "RSI14Trend50"))

        # MACD signal-line crossover.
        if macd[i] > macd_signal[i] and macd[i - 1] <= macd_signal[i - 1]:
            signals.append(Signal(i, 1, "MACD12x26"))
        elif macd[i] < macd_signal[i] and macd[i - 1] >= macd_signal[i - 1]:
            signals.append(Signal(i, -1, "MACD12x26"))

        # Keltner breakout uses ATR known at this completed candle.
        if keltner_upper[i] is not None and keltner_upper[i - 1] is not None:
            if rows[i].close > keltner_upper[i] and rows[i - 1].close <= keltner_upper[i - 1]:
                signals.append(Signal(i, 1, "Keltner20x2ATR"))
            elif rows[i].close < keltner_lower[i] and rows[i - 1].close >= keltner_lower[i - 1]:
                signals.append(Signal(i, -1, "Keltner20x2ATR"))
    return signals


def backtest(candles: list[Candle], signals: list[Signal],
             config: BacktestConfig = BacktestConfig()) -> list[Trade]:
    """One non-overlapping trade per symbol; conservative same-bar stop-first.

    Signals use close[i], entry uses open[i+1]. Stop gaps fill at the open;
    intrabar stop fills at stop. Targets fill at target. Open terminal trades
    are explicitly marked OPEN and have no realized net_return.
    """
    rows = validate_candles(candles)
    if (not math.isfinite(config.fee_per_side) or not math.isfinite(config.slippage_per_side)
            or not 0 <= config.fee_per_side < 1 or not 0 <= config.slippage_per_side < 1):
        raise ValueError("Fees and slippage must be finite and between 0 and 1")
    if config.max_bars is not None and config.max_bars < 1:
        raise ValueError("max_bars must be >= 1 or None")
    for pct in (config.stop_pct, config.target_pct):
        if pct is not None and not (0 < pct < 1):
            raise ValueError("Stop/target percentages must be between 0 and 1")
    ordered = sorted(signals, key=lambda s: (s.index, s.strategy, -s.direction))
    trades: list[Trade] = []
    # Each strategy is simulated independently; cross-strategy signals do not compete.
    available_after: dict[str, int] = {}
    for signal in ordered:
        if signal.direction not in (-1, 1) or signal.index < 0 or signal.index + 1 >= len(rows):
            continue
        entry_idx = signal.index + 1
        if entry_idx <= available_after.get(signal.strategy, -1):
            continue
        entry = rows[entry_idx].open
        entry_fill = entry * (1.0 + signal.direction * config.slippage_per_side)
        stop = entry_fill * (1.0 - signal.direction * config.stop_pct) if config.stop_pct else None
        target = entry_fill * (1.0 + signal.direction * config.target_pct) if config.target_pct else None
        last_idx = min(len(rows) - 1, entry_idx + config.max_bars - 1) if config.max_bars else len(rows) - 1
        exit_idx, exit_price, reason = None, None, "OPEN"
        for j in range(entry_idx, last_idx + 1):
            bar = rows[j]
            if signal.direction == 1:
                if stop is not None and bar.open <= stop:
                    exit_idx, exit_price, reason = j, bar.open, "STOP_GAP"
                elif target is not None and bar.open >= target:
                    exit_idx, exit_price, reason = j, target, "TARGET_GAP"
                elif stop is not None and bar.low <= stop:
                    exit_idx, exit_price, reason = j, stop, "STOP"
                elif target is not None and bar.high >= target:
                    exit_idx, exit_price, reason = j, target, "TARGET"
            else:
                if stop is not None and bar.open >= stop:
                    exit_idx, exit_price, reason = j, bar.open, "STOP_GAP"
                elif target is not None and bar.open <= target:
                    exit_idx, exit_price, reason = j, target, "TARGET_GAP"
                elif stop is not None and bar.high >= stop:
                    exit_idx, exit_price, reason = j, stop, "STOP"
                elif target is not None and bar.low <= target:
                    exit_idx, exit_price, reason = j, target, "TARGET"
            if exit_idx is not None:
                break
        if exit_idx is None and config.max_bars and last_idx < len(rows) - 1:
            exit_idx, exit_price, reason = last_idx, rows[last_idx].close, "TIME"
        if exit_idx is None:
            trades.append(Trade(signal.strategy, signal.direction, rows[signal.index].timestamp,
                                rows[entry_idx].timestamp, None, entry_fill, None, None, "OPEN", "END_OF_DATA"))
            available_after[signal.strategy] = len(rows) - 1
        else:
            # Adverse slippage is applied to both fills; fees are charged on both
            # entry and exit notionals. Trade prices record modeled fill prices.
            exit_fill = exit_price * (1.0 - signal.direction * config.slippage_per_side)
            gross = signal.direction * (exit_fill - entry_fill) / entry_fill
            fee_cost = config.fee_per_side * (entry_fill + exit_fill) / entry_fill
            net = gross - fee_cost
            trades.append(Trade(signal.strategy, signal.direction, rows[signal.index].timestamp,
                                rows[entry_idx].timestamp, rows[exit_idx].timestamp,
                                entry_fill, exit_fill, net, "CLOSED", reason))
            available_after[signal.strategy] = exit_idx
    return trades


def summarize(trades: list[Trade]) -> dict:
    closed = [t.net_return for t in trades if t.status == "CLOSED" and t.net_return is not None]
    opened = sum(t.status == "OPEN" for t in trades)
    wins = [x for x in closed if x > 0]
    losses = [x for x in closed if x <= 0]
    loss_abs = abs(sum(losses))
    return {
        "closed_trades": len(closed),
        "open_terminal_trades_excluded": opened,
        "win_rate": len(wins) / len(closed) if closed else None,
        "average_net_return": sum(closed) / len(closed) if closed else None,
        "profit_factor": sum(wins) / loss_abs if loss_abs else None,
        "profit_factor_infinite": bool(wins) and not loss_abs,
        "sum_trade_returns_not_portfolio_return": sum(closed) if closed else 0.0,
    }
