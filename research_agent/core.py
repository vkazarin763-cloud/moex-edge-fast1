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
    """Validate OHLCV and monotonic timestamps without silently mixing timezones.

    Naive timestamps (as returned by MOEX ISS) remain naive exchange-local values.
    A dataset may use all-naive or all-timezone-aware timestamps, but never a mix.
    """
    rows = list(candles)
    if not rows:
        raise ValueError("No candles supplied")
    previous = None
    timezone_aware = None
    for i, c in enumerate(rows):
        if not isinstance(c.timestamp, datetime):
            raise ValueError(f"Timestamp must be datetime at row {i}")
        try:
            aware = c.timestamp.tzinfo is not None and c.timestamp.utcoffset() is not None
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid timestamp timezone at row {i}: {exc}") from exc
        if timezone_aware is None:
            timezone_aware = aware
        elif aware != timezone_aware:
            raise ValueError(f"Mixed timezone-aware and naive timestamps at row {i}")
        values = (c.open, c.high, c.low, c.close, c.volume)
        if not all(math.isfinite(x) for x in values):
            raise ValueError(f"Non-finite OHLCV at row {i}")
        if min(c.open, c.high, c.low, c.close) <= 0 or c.volume < 0:
            raise ValueError(f"Non-positive price or negative volume at row {i}")
        if c.high < max(c.open, c.close, c.low) or c.low > min(c.open, c.close, c.high):
            raise ValueError(f"Invalid OHLC relationship at row {i}")
        if previous is not None:
            try:
                out_of_order = c.timestamp <= previous
            except TypeError as exc:
                raise ValueError(f"Incomparable timestamps at row {i}: {exc}") from exc
            if out_of_order:
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


def _sma(values: list[float], period: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = sum(values[i-period+1:i+1]) / period
    return out


def _rolling_std(values: list[float], period: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i-period+1:i+1]
        mean = sum(window) / period
        out[i] = math.sqrt(sum((x-mean)**2 for x in window) / period)
    return out


def _wilder_adx(rows: list[Candle], period: int = 14):
    plus_dm, minus_dm, tr = [0.0], [0.0], [rows[0].high - rows[0].low]
    for i in range(1, len(rows)):
        up = rows[i].high - rows[i-1].high
        down = rows[i-1].low - rows[i].low
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr.append(max(rows[i].high-rows[i].low, abs(rows[i].high-rows[i-1].close), abs(rows[i].low-rows[i-1].close)))
    pdi: list[Optional[float]] = [None] * len(rows)
    mdi: list[Optional[float]] = [None] * len(rows)
    adx: list[Optional[float]] = [None] * len(rows)
    if len(rows) < period * 2:
        return adx, pdi, mdi
    sm_tr, sm_plus, sm_minus = sum(tr[1:period+1]), sum(plus_dm[1:period+1]), sum(minus_dm[1:period+1])
    dx_values = []
    for i in range(period, len(rows)):
        if i > period:
            sm_tr = sm_tr - sm_tr/period + tr[i]
            sm_plus = sm_plus - sm_plus/period + plus_dm[i]
            sm_minus = sm_minus - sm_minus/period + minus_dm[i]
        pdi[i] = 100*sm_plus/sm_tr if sm_tr else 0.0
        mdi[i] = 100*sm_minus/sm_tr if sm_tr else 0.0
        denom = (pdi[i] or 0.0) + (mdi[i] or 0.0)
        dx_values.append(100*abs((pdi[i] or 0.0)-(mdi[i] or 0.0))/denom if denom else 0.0)
        if len(dx_values) == period:
            adx[i] = sum(dx_values)/period
        elif len(dx_values) > period:
            prev = next((adx[j] for j in range(i-1, -1, -1) if adx[j] is not None), None)
            if prev is not None:
                adx[i] = (prev*(period-1)+dx_values[-1])/period
    return adx, pdi, mdi


def generate_signals(candles: list[Candle]) -> list[Signal]:
    """Broad, fixed-rule TA candidate library. No parameter fitting or look-ahead."""
    rows = validate_candles(candles)
    closes = [c.close for c in rows]
    ema12, ema20, ema26, ema50 = (_ema(closes, 12), _ema(closes, 20), _ema(closes, 26), _ema(closes, 50))
    macd = [a - b for a, b in zip(ema12, ema26)]
    macd_signal = _ema(macd, 9)
    rsi = _wilder_rsi(closes, 14)
    atr = _wilder_atr(rows, 14)
    upper_k = [ema20[i] + 2 * atr[i] if atr[i] is not None else None for i in range(len(rows))]
    lower_k = [ema20[i] - 2 * atr[i] if atr[i] is not None else None for i in range(len(rows))]
    bb_mid = _sma(closes, 20)
    bb_std = _rolling_std(closes, 20)
    bb_upper = [bb_mid[i] + 2 * bb_std[i] if bb_mid[i] is not None else None for i in range(len(rows))]
    bb_lower = [bb_mid[i] - 2 * bb_std[i] if bb_mid[i] is not None else None for i in range(len(rows))]
    adx, plus_di, minus_di = _wilder_adx(rows, 14)
    avg_volume = _sma([c.volume for c in rows], 20)
    signals: list[Signal] = []
    for i in range(55, len(rows) - 1):
        prior = rows[i-20:i]
        prior_high, prior_low = max(c.high for c in prior), min(c.low for c in prior)
        c, p = rows[i], rows[i-1]
        # Trend and momentum
        if ema20[i] > ema50[i] and ema20[i-1] <= ema50[i-1]:
            signals.append(Signal(i, 1, "EMA20x50"))
        elif ema20[i] < ema50[i] and ema20[i-1] >= ema50[i-1]:
            signals.append(Signal(i, -1, "EMA20x50"))
        if rsi[i] is not None and rsi[i-1] is not None:
            if ema20[i] > ema50[i] and rsi[i] > 50 >= rsi[i-1]:
                signals.append(Signal(i, 1, "RSI14Trend50"))
            elif ema20[i] < ema50[i] and rsi[i] < 50 <= rsi[i-1]:
                signals.append(Signal(i, -1, "RSI14Trend50"))
        if macd[i] > macd_signal[i] and macd[i-1] <= macd_signal[i-1]:
            signals.append(Signal(i, 1, "MACD12x26"))
        elif macd[i] < macd_signal[i] and macd[i-1] >= macd_signal[i-1]:
            signals.append(Signal(i, -1, "MACD12x26"))
        if adx[i] is not None and adx[i] >= 20:
            if plus_di[i] > minus_di[i] and plus_di[i-1] <= minus_di[i-1]:
                signals.append(Signal(i, 1, "ADX14Trend"))
            elif minus_di[i] > plus_di[i] and minus_di[i-1] <= plus_di[i-1]:
                signals.append(Signal(i, -1, "ADX14Trend"))
        # Breakouts and volatility
        if c.close > prior_high:
            signals.append(Signal(i, 1, "Donchian20"))
        elif c.close < prior_low:
            signals.append(Signal(i, -1, "Donchian20"))
        if upper_k[i] is not None and upper_k[i-1] is not None:
            if c.close > upper_k[i] and p.close <= upper_k[i-1]:
                signals.append(Signal(i, 1, "Keltner20x2ATR"))
            elif c.close < lower_k[i] and p.close >= lower_k[i-1]:
                signals.append(Signal(i, -1, "Keltner20x2ATR"))
        if bb_upper[i] is not None and bb_upper[i-1] is not None:
            if c.close > bb_upper[i] and p.close <= bb_upper[i-1]:
                signals.append(Signal(i, 1, "Bollinger20x2"))
            elif c.close < bb_lower[i] and p.close >= bb_lower[i-1]:
                signals.append(Signal(i, -1, "Bollinger20x2"))
        if avg_volume[i] and c.volume > 1.5 * avg_volume[i]:
            if c.close > prior_high:
                signals.append(Signal(i, 1, "VolumeBreakout"))
            elif c.close < prior_low:
                signals.append(Signal(i, -1, "VolumeBreakout"))
        # Breakout retest: prior breakout within five completed bars, retest and reclaim
        if i >= 26:
            resistance = max(bar.high for bar in rows[i-25:i-5])
            support = min(bar.low for bar in rows[i-25:i-5])
            broke_up = any(rows[j].close > resistance for j in range(i-5, i))
            broke_down = any(rows[j].close < support for j in range(i-5, i))
            if broke_up and c.low <= resistance * 1.01 and c.close > resistance:
                signals.append(Signal(i, 1, "BreakoutRetest"))
            elif broke_down and c.high >= support * 0.99 and c.close < support:
                signals.append(Signal(i, -1, "BreakoutRetest"))
        # Candlestick reversal patterns in direction of prevailing short trend
        body = abs(c.close - c.open)
        prev_body = abs(p.close - p.open)
        if body > 0 and prev_body > 0:
            bullish_engulf = p.close < p.open and c.close > c.open and c.open <= p.close and c.close >= p.open
            bearish_engulf = p.close > p.open and c.close < c.open and c.open >= p.close and c.close <= p.open
            if bullish_engulf and ema20[i] > ema50[i]:
                signals.append(Signal(i, 1, "EngulfingTrend"))
            elif bearish_engulf and ema20[i] < ema50[i]:
                signals.append(Signal(i, -1, "EngulfingTrend"))
        candle_range = c.high - c.low
        if candle_range > 0:
            lower_wick = min(c.open, c.close) - c.low
            upper_wick = c.high - max(c.open, c.close)
            if lower_wick >= 2 * max(body, candle_range * 0.05) and c.close > c.open and ema20[i] > ema50[i]:
                signals.append(Signal(i, 1, "PinBarTrend"))
            elif upper_wick >= 2 * max(body, candle_range * 0.05) and c.close < c.open and ema20[i] < ema50[i]:
                signals.append(Signal(i, -1, "PinBarTrend"))
        # Volatility squeeze: narrowest Bollinger width of the prior 20 bars, then range break
        if bb_upper[i] is not None and bb_mid[i] and bb_mid[i] > 0:
            width = (bb_upper[i] - bb_lower[i]) / bb_mid[i]
            prior_widths = []
            for j in range(i-20, i):
                if bb_upper[j] is not None and bb_mid[j] and bb_mid[j] > 0:
                    prior_widths.append((bb_upper[j] - bb_lower[j]) / bb_mid[j])
            if prior_widths and width <= min(prior_widths) and c.close > prior_high:
                signals.append(Signal(i, 1, "SqueezeBreakout"))
            elif prior_widths and width <= min(prior_widths) and c.close < prior_low:
                signals.append(Signal(i, -1, "SqueezeBreakout"))
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
        # If the full bar horizon is present, time-exit even when it ends on the final dataset bar.
        horizon_end = entry_idx + config.max_bars - 1 if config.max_bars else None
        if exit_idx is None and horizon_end is not None and horizon_end < len(rows):
            exit_idx, exit_price, reason = last_idx, rows[last_idx].close, "TIME"
        if exit_idx is None:
            trades.append(Trade(signal.strategy, signal.direction, rows[signal.index].timestamp,
                                rows[entry_idx].timestamp, None, entry_fill, None, None, "OPEN", "END_OF_DATA"))
            available_after[signal.strategy] = len(rows) - 1
        else:
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
