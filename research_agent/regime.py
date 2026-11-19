"""Causal cross-sectional market-regime labels for descriptive research only."""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import timedelta
import math
from typing import Any

from .core import Candle, Trade, validate_candles


def _ema(values: list[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1.0)
    current = values[0]
    result = []
    for value in values:
        current = alpha * value + (1.0 - alpha) * current
        result.append(current)
    return result


def _trade_stats(trades: list[Trade]) -> dict[str, Any]:
    closed = [
        float(item.net_return) for item in trades
        if item.status == "CLOSED" and item.net_return is not None
    ]
    wins = [value for value in closed if value > 0]
    losses = [value for value in closed if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "closed_trades": len(closed),
        "open_trades_excluded": sum(item.status != "CLOSED" for item in trades),
        "win_rate": len(wins) / len(closed) if closed else None,
        "average_net_return": sum(closed) / len(closed) if closed else None,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "profit_factor_infinite": bool(gross_profit) and not gross_loss,
        "sum_trade_returns_not_portfolio_return": sum(closed),
    }


def market_breadth_regime_report(
    candles_by_ticker: dict[str, list[Candle]],
    trades: list[tuple[str, Trade]],
    min_tickers: int = 20,
    bullish_threshold: float = 0.60,
    bearish_threshold: float = 0.40,
    max_staleness_days: int = 3,
) -> dict[str, Any]:
    """Classify market breadth using only information available at each daily close.

    A ticker is trend-positive when close > EMA200 and EMA50 > EMA200.
    Breadth >= bullish_threshold is BULLISH; breadth <= bearish_threshold is
    BEARISH; the interval between them is NEUTRAL. Dates with fewer than
    min_tickers eligible observations are not classified. Each trade is assigned
    the most recent available breadth label at or before its signal close, subject
    to max_staleness_days. This is descriptive regime stratification, not a signal.
    """
    if min_tickers < 1:
        raise ValueError("min_tickers must be positive")
    if not (0.0 <= bearish_threshold < bullish_threshold <= 1.0):
        raise ValueError("thresholds must satisfy 0 <= bearish < bullish <= 1")
    if max_staleness_days < 0:
        raise ValueError("max_staleness_days must be non-negative")
    if not candles_by_ticker:
        raise ValueError("candles_by_ticker must not be empty")

    breadth: dict[Any, list[bool]] = defaultdict(list)
    tickers_with_ema_history = 0
    for ticker, candles in sorted(candles_by_ticker.items()):
        rows = validate_candles(candles)
        if len(rows) < 200:
            continue
        closes = [row.close for row in rows]
        ema50 = _ema(closes, 50)
        ema200 = _ema(closes, 200)
        tickers_with_ema_history += 1
        for index in range(199, len(rows)):
            breadth[rows[index].timestamp].append(
                closes[index] > ema200[index] and ema50[index] > ema200[index]
            )

    observations = []
    for timestamp in sorted(breadth):
        states = breadth[timestamp]
        count = len(states)
        if count < min_tickers:
            regime = "UNKNOWN"
            ratio = None
        else:
            ratio = sum(states) / count
            if ratio >= bullish_threshold:
                regime = "BULLISH"
            elif ratio <= bearish_threshold:
                regime = "BEARISH"
            else:
                regime = "NEUTRAL"
        observations.append({
            "timestamp": timestamp,
            "eligible_tickers": count,
            "bullish_breadth": ratio,
            "regime": regime,
        })

    observation_times = [item["timestamp"] for item in observations]
    assigned: dict[str, list[Trade]] = defaultdict(list)
    for ticker, trade in trades:
        index = bisect_right(observation_times, trade.signal_time) - 1
        regime = "UNKNOWN"
        if index >= 0:
            observation = observations[index]
            age = trade.signal_time.date() - observation["timestamp"].date()
            if age <= timedelta(days=max_staleness_days):
                regime = observation["regime"]
        assigned[regime].append(trade)

    regimes = ("BULLISH", "NEUTRAL", "BEARISH", "UNKNOWN")
    by_regime = {regime: _trade_stats(assigned[regime]) for regime in regimes}
    by_strategy: dict[str, dict[str, dict[str, Any]]] = {}
    strategy_names = sorted({trade.strategy for _, trade in trades})
    for strategy in strategy_names:
        by_strategy[strategy] = {}
        for regime in regimes:
            selected = [
                trade for ticker, trade in trades
                if trade.strategy == strategy
                and trade in assigned[regime]
            ]
            by_strategy[strategy][regime] = _trade_stats(selected)

    return {
        "status": "DESCRIPTIVE_DEVELOPMENT_REGIME_ANALYSIS",
        "method": "cross-sectional breadth: close > EMA200 and EMA50 > EMA200",
        "parameters": {
            "ema_fast": 50,
            "ema_slow": 200,
            "min_tickers": min_tickers,
            "bullish_threshold": bullish_threshold,
            "bearish_threshold": bearish_threshold,
            "max_staleness_days": max_staleness_days,
        },
        "tickers_with_ema_history": tickers_with_ema_history,
        "breadth_observations": len(observations),
        "regime_observations": {
            regime: sum(item["regime"] == regime for item in observations)
            for regime in regimes
        },
        "by_regime": by_regime,
        "by_strategy": by_strategy,
        "warning": "Descriptive, development-only stratification. Breadth uses same-close information available at signal time; it is not a predictive feature, optimized filter, independent validation, or evidence of profitability. Trade-return sums are not portfolio returns.",
    }
