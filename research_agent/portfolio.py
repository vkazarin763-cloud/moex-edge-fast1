"""Research-only event-driven portfolio simulation over closed strategy trades.

The engine accepts trades produced by an out-of-sample process. It does not
fetch data, generate signals, place orders, or interact with production state.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .core import Trade


@dataclass(frozen=True)
class PortfolioTrade:
    ticker: str
    trade: Trade


def simulate_portfolio(
    candidates: Iterable[PortfolioTrade],
    max_positions: int = 10,
) -> dict:
    """Simulate a cash-only portfolio with equal risk-neutral slot allocation.

    Initial equity is normalized to 1.0 (not RUB). At each accepted entry,
    notional is min(available cash, current equity / max_positions). Only one
    position per ticker is allowed. If several entries share a timestamp,
    ticker then strategy order breaks ties deterministically. Exits of positions
    already open are processed before new entries; a trade whose entry and exit
    share a timestamp is entered first and closed immediately afterward.

    Trade net_return must already include the chosen fee/slippage assumptions.
    Only fully closed trades are eligible; open terminal trades are counted and
    excluded. This is a realized-P&L simulation, not mark-to-market accounting.
    """
    if not isinstance(max_positions, int) or isinstance(max_positions, bool) or max_positions < 1:
        raise ValueError("max_positions must be a positive integer")

    valid: list[PortfolioTrade] = []
    excluded_open = 0
    for candidate in candidates:
        if not candidate.ticker or candidate.ticker.strip() != candidate.ticker:
            raise ValueError("ticker must be a non-empty trimmed string")
        trade = candidate.trade
        if trade.status != "CLOSED" or trade.exit_time is None or trade.net_return is None:
            excluded_open += 1
            continue
        if not math.isfinite(trade.net_return) or trade.net_return <= -1.0:
            raise ValueError("closed trade net_return must be finite and greater than -100%")
        if trade.entry_time > trade.exit_time:
            raise ValueError("trade entry_time must not be after exit_time")
        valid.append(candidate)

    # A unified sort also validates that all timestamps are mutually comparable.
    events = []
    for sequence, candidate in enumerate(valid):
        trade = candidate.trade
        events.append((trade.entry_time, 1, candidate.ticker, trade.strategy, sequence, "ENTRY", candidate))
        exit_priority = 0 if trade.exit_time > trade.entry_time else 2
        events.append((trade.exit_time, exit_priority, candidate.ticker, trade.strategy, sequence, "EXIT", candidate))
    events.sort(key=lambda event: event[:5])

    cash = 1.0
    active_by_ticker: dict[str, dict] = {}
    active_by_sequence: dict[int, dict] = {}
    accepted = 0
    skipped_position_limit = 0
    skipped_ticker_overlap = 0
    equity_peak = 1.0
    max_drawdown = 0.0
    max_concurrent = 0
    equity_curve = [{"timestamp": events[0][0].isoformat(), "equity": 1.0, "drawdown": 0.0}] if events else []
    position_seconds = 0.0
    total_seconds = 0.0
    previous_time = events[0][0] if events else None
    realized_returns: list[float] = []
    completed_pnl: list[float] = []

    for timestamp, _, ticker, strategy, sequence, kind, candidate in events:
        if previous_time is not None:
            elapsed = (timestamp - previous_time).total_seconds()
            if elapsed < 0:
                raise ValueError("portfolio events are not chronological")
            if elapsed:
                total_seconds += elapsed
                position_seconds += elapsed * len(active_by_sequence)
        previous_time = timestamp

        if kind == "EXIT":
            position = active_by_sequence.pop(sequence, None)
            # A rejected entry has no position and therefore no matching exit.
            if position is None:
                continue
            active_by_ticker.pop(ticker, None)
            trade_return = candidate.trade.net_return
            pnl = position["notional"] * trade_return
            cash += position["notional"] + pnl
            realized_returns.append(trade_return)
            completed_pnl.append(pnl)
            equity = cash + sum(p["notional"] for p in active_by_sequence.values())
            equity_peak = max(equity_peak, equity)
            drawdown = equity / equity_peak - 1.0 if equity_peak else 0.0
            max_drawdown = min(max_drawdown, drawdown)
            equity_curve.append({
                "timestamp": timestamp.isoformat(),
                "equity": equity,
                "drawdown": drawdown,
                "pnl": pnl,
            })
            continue

        if ticker in active_by_ticker:
            skipped_ticker_overlap += 1
            continue
        if len(active_by_sequence) >= max_positions:
            skipped_position_limit += 1
            continue

        equity = cash + sum(p["notional"] for p in active_by_sequence.values())
        notional = min(cash, equity / max_positions)
        if notional <= 0:
            skipped_position_limit += 1
            continue
        cash -= notional
        position = {"ticker": ticker, "strategy": strategy, "notional": notional}
        active_by_ticker[ticker] = position
        active_by_sequence[sequence] = position
        accepted += 1
        max_concurrent = max(max_concurrent, len(active_by_sequence))

    final_equity = cash + sum(p["notional"] for p in active_by_sequence.values())
    gross_profit = sum(x for x in completed_pnl if x > 0)
    gross_loss = abs(sum(x for x in completed_pnl if x < 0))
    return {
        "method": "event-driven cash-only simulation; equal notional per available position slot",
        "initial_equity_normalized": 1.0,
        "final_equity_normalized": final_equity,
        "total_return": final_equity - 1.0,
        "max_drawdown": max_drawdown,
        "closed_trades_accepted": accepted,
        "open_or_incomplete_trades_excluded": excluded_open,
        "skipped_position_limit": skipped_position_limit,
        "skipped_ticker_overlap": skipped_ticker_overlap,
        "max_positions": max_positions,
        "max_concurrent_positions": max_concurrent,
        "average_concurrent_positions": position_seconds / total_seconds if total_seconds else 0.0,
        "position_slot_utilization": (
            position_seconds / (total_seconds * max_positions)
            if total_seconds else 0.0
        ),
        "win_rate": (
            sum(r > 0 for r in realized_returns) / len(realized_returns)
            if realized_returns else None
        ),
        "average_trade_net_return": (
            sum(realized_returns) / len(realized_returns)
            if realized_returns else None
        ),
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "profit_factor_infinite": bool(gross_profit) and not gross_loss,
        "equity_curve": equity_curve,
        "limitations": [
            "normalized equity, not a RUB account forecast",
            "no mark-to-market valuation of open positions",
            "only closed trades are eligible",
            "one open position per ticker; no leverage or short-sale collateral model",
            "entry allocation is equal-slot notional, not stop-risk sizing",
            "candidate trades must come from a separate out-of-sample evaluation",
        ],
    }


def compare_position_limits(
    candidates: Iterable[PortfolioTrade],
    limits: tuple[int, ...] = (5, 7, 10),
) -> dict:
    """Run the same immutable candidate trade stream under several position caps."""
    rows = list(candidates)
    if not limits or len(set(limits)) != len(limits):
        raise ValueError("limits must be a non-empty tuple of unique integers")
    return {
        "method": "same candidate trades replayed independently for each position cap",
        "comparisons": {
            str(limit): simulate_portfolio(rows, max_positions=limit)
            for limit in limits
        },
    }
