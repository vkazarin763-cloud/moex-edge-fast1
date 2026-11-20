"""Causal mark-to-market diagnostics for the research-only portfolio simulator.

Daily/intraday candles are used strictly as-of each portfolio timestamp. A mark
must be newer than the position entry and no older than the configured limit.
Missing/stale marks make MTM equity unavailable rather than silently carrying
an old price forward.
"""
from __future__ import annotations

import bisect
import math
from datetime import datetime
from typing import Iterable

from .core import Candle, Trade, validate_candles
from .portfolio import PortfolioTrade


def simulate_mark_to_market(
    candidates: Iterable[PortfolioTrade],
    candles_by_ticker: dict[str, list[Candle]],
    max_positions: int = 10,
    max_mark_staleness_days: float = 3.0,
    fee_per_side: float = 0.001,
    slippage_per_side: float = 0.0005,
    include_equity_curve: bool = True,
) -> dict:
    """Replay closed candidate trades while marking open positions to market.

    Entry sizing follows the existing normalized cash-only equal-slot model.
    At each timestamp, exits are realized before new entries. Position marks
    use the latest candle timestamp <= the portfolio timestamp, but strictly
    after entry_time, so a daily bar stamped at the entry date cannot leak its
    eventual close into an entry-time valuation. No future candle is used.

    Marked liquidation value estimates exit slippage and both fee sides.
    Closed positions use their exact backtest net_return at exit. If any active
    position lacks a fresh post-entry mark, portfolio MTM equity is None for
    that timestamp and is excluded from MTM drawdown updates.
    """
    if not isinstance(max_positions, int) or isinstance(max_positions, bool) or max_positions < 1:
        raise ValueError("max_positions must be a positive integer")
    if not math.isfinite(max_mark_staleness_days) or max_mark_staleness_days < 0:
        raise ValueError("max_mark_staleness_days must be finite and >= 0")
    if (not math.isfinite(fee_per_side) or not 0 <= fee_per_side < 1
            or not math.isfinite(slippage_per_side) or not 0 <= slippage_per_side < 1):
        raise ValueError("fee and slippage must be finite and between 0 and 1")

    rows_by_ticker: dict[str, list[Candle]] = {}
    times_by_ticker: dict[str, list[datetime]] = {}
    for ticker, rows in sorted(candles_by_ticker.items()):
        if not ticker or ticker.strip() != ticker:
            raise ValueError("candle ticker keys must be non-empty trimmed strings")
        clean = validate_candles(rows)
        rows_by_ticker[ticker] = clean
        times_by_ticker[ticker] = [c.timestamp for c in clean]

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

    events_by_time: dict[datetime, list[tuple[int, str, str, int, str, PortfolioTrade]]] = {}
    first_entry = min((item.trade.entry_time for item in valid), default=None)
    for sequence, candidate in enumerate(valid):
        trade = candidate.trade
        events_by_time.setdefault(trade.entry_time, []).append(
            (1, candidate.ticker, trade.strategy, sequence, "ENTRY", candidate)
        )
        # Match simulate_portfolio: exits normally precede entries; a
        # zero-duration trade enters and exits before the next same-time entry.
        exit_priority = 0 if trade.exit_time > trade.entry_time else 1
        events_by_time.setdefault(trade.exit_time, []).append(
            (exit_priority, candidate.ticker, trade.strategy, sequence, "EXIT", candidate)
        )

    market_times = {
        timestamp
        for rows in rows_by_ticker.values()
        for timestamp in (c.timestamp for c in rows)
        if first_entry is not None and timestamp >= first_entry
    }
    timeline = sorted(set(events_by_time) | market_times)

    cash = 1.0
    active_by_ticker: dict[str, dict] = {}
    active_by_sequence: dict[int, dict] = {}
    accepted = 0
    skipped_position_limit = 0
    skipped_ticker_overlap = 0
    realized_peak = 1.0
    mtm_peak = 1.0
    max_realized_drawdown = 0.0
    max_mtm_drawdown = 0.0
    realized_returns: list[float] = []
    snapshots: list[dict] = []

    for timestamp in timeline:
        events = sorted(events_by_time.get(timestamp, []), key=lambda item: item[:5])
        for priority, ticker, strategy, sequence, kind, candidate in events:
            trade = candidate.trade
            if kind == "EXIT":
                position = active_by_sequence.pop(sequence, None)
                if position is None:
                    continue
                active_by_ticker.pop(ticker, None)
                pnl = position["notional"] * trade.net_return
                cash += position["notional"] + pnl
                realized_returns.append(trade.net_return)
                continue

            if ticker in active_by_ticker:
                skipped_ticker_overlap += 1
                continue
            if len(active_by_sequence) >= max_positions:
                skipped_position_limit += 1
                continue
            realized_equity_before_entry = cash + sum(
                p["notional"] for p in active_by_sequence.values()
            )
            notional = min(cash, realized_equity_before_entry / max_positions)
            if notional <= 0:
                skipped_position_limit += 1
                continue
            cash -= notional
            position = {
                "ticker": ticker,
                "strategy": strategy,
                "notional": notional,
                "trade": trade,
            }
            active_by_ticker[ticker] = position
            active_by_sequence[sequence] = position
            accepted += 1

        realized_equity = cash + sum(p["notional"] for p in active_by_sequence.values())
        realized_peak = max(realized_peak, realized_equity)
        realized_drawdown = realized_equity / realized_peak - 1.0 if realized_peak else 0.0
        max_realized_drawdown = min(max_realized_drawdown, realized_drawdown)

        unrealized_pnl = 0.0
        unmarked: list[dict] = []
        for position in active_by_sequence.values():
            ticker = position["ticker"]
            trade = position["trade"]
            ticker_times = times_by_ticker.get(ticker, [])
            ticker_rows = rows_by_ticker.get(ticker, [])
            mark_index = bisect.bisect_right(ticker_times, timestamp) - 1
            if mark_index < 0:
                unmarked.append({
                    "ticker": ticker,
                    "reason": "NO_CANDLE_AT_OR_BEFORE_AS_OF_TIME",
                    "last_mark_time": None,
                    "age_days": None,
                })
                continue
            mark = ticker_rows[mark_index]
            age_days = (timestamp - mark.timestamp).total_seconds() / 86400.0
            if mark.timestamp <= trade.entry_time:
                reason = "NO_POST_ENTRY_CANDLE"
            elif age_days < 0:
                reason = "FUTURE_MARK_REJECTED"
            elif age_days > max_mark_staleness_days:
                reason = "STALE_MARK"
            else:
                reason = None
            if reason is not None:
                unmarked.append({
                    "ticker": ticker,
                    "reason": reason,
                    "last_mark_time": mark.timestamp.isoformat(),
                    "age_days": age_days,
                })
                continue

            direction = trade.direction
            estimated_exit_fill = mark.close * (1.0 - direction * slippage_per_side)
            gross_return = direction * (estimated_exit_fill - trade.entry_price) / trade.entry_price
            estimated_fee = fee_per_side * (
                trade.entry_price + estimated_exit_fill
            ) / trade.entry_price
            estimated_net_return = gross_return - estimated_fee
            unrealized_pnl += position["notional"] * estimated_net_return

        mtm_equity = None if unmarked else realized_equity + unrealized_pnl
        mtm_drawdown = None
        if mtm_equity is not None:
            mtm_peak = max(mtm_peak, mtm_equity)
            mtm_drawdown = mtm_equity / mtm_peak - 1.0 if mtm_peak else 0.0
            max_mtm_drawdown = min(max_mtm_drawdown, mtm_drawdown)

        snapshots.append({
            "timestamp": timestamp.isoformat(),
            "realized_equity": realized_equity,
            "realized_drawdown": realized_drawdown,
            "mark_to_market_equity": mtm_equity,
            "unrealized_pnl": None if unmarked else unrealized_pnl,
            "mark_to_market_drawdown": mtm_drawdown,
            "unmarked_positions": unmarked,
            "active_positions": len(active_by_sequence),
        })

    final_realized_equity = cash + sum(
        p["notional"] for p in active_by_sequence.values()
    )
    final_snapshot = snapshots[-1] if snapshots else None
    return {
        "status": "RESEARCH_MARK_TO_MARKET_DIAGNOSTIC",
        "method": "causal as-of candle marks; estimated liquidation costs; cash-only equal-slot allocation",
        "initial_equity_normalized": 1.0,
        "final_realized_equity_normalized": final_realized_equity,
        "final_realized_return": final_realized_equity - 1.0,
        "final_mark_to_market_equity_normalized": (
            final_snapshot["mark_to_market_equity"] if final_snapshot else 1.0
        ),
        "max_realized_drawdown": max_realized_drawdown,
        "max_mark_to_market_drawdown": max_mtm_drawdown,
        "closed_trades_accepted": accepted,
        "open_or_incomplete_trades_excluded": excluded_open,
        "skipped_position_limit": skipped_position_limit,
        "skipped_ticker_overlap": skipped_ticker_overlap,
        "max_positions": max_positions,
        "max_mark_staleness_days": max_mark_staleness_days,
        "fee_per_side_for_marks": fee_per_side,
        "slippage_per_side_for_marks": slippage_per_side,
        "final_unmarked_positions": (
            final_snapshot["unmarked_positions"] if final_snapshot else []
        ),
        "equity_curve": snapshots if include_equity_curve else [],
        "equity_curve_points": len(snapshots),
        "limitations": [
            "normalized equity, not a RUB account forecast",
            "open-position marks estimate liquidation using configured fees and slippage",
            "daily bars stamped on the entry date are deliberately not used to mark that position",
            "stale or missing marks make MTM equity unavailable; they are never forward-filled silently",
            "closed positions use the exact net return from the candidate backtest",
            "this is a diagnostic overlay, not an execution or liquidation engine",
        ],
    }
