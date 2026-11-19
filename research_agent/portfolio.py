"""Research-only event-driven portfolio simulation over closed strategy trades.

The engine accepts closed trades from the isolated research pipeline. It does
not place orders or interact with production state.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .core import BacktestConfig, Candle, Trade, backtest, generate_signals, validate_candles


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
        exit_priority = 0 if trade.exit_time > trade.entry_time else 1
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
            "portfolio conclusions inherit the validation limits of the candidate trade-generation process",
        ],
    }


def compare_position_limits(
    candidates: Iterable[PortfolioTrade],
    limits: tuple[int, ...] = (5, 7, 10),
) -> dict:
    """Run the same immutable candidate trade stream under several position caps."""
    rows = list(candidates)
    if not limits or any(
        not isinstance(limit, int) or isinstance(limit, bool) or limit < 1
        for limit in limits
    ):
        raise ValueError("limits must be a non-empty tuple of positive integers")
    if len(set(limits)) != len(limits):
        raise ValueError("limits must be unique")
    return {
        "method": "same candidate trades replayed independently for each position cap",
        "comparisons": {
            str(limit): simulate_portfolio(rows, max_positions=limit)
            for limit in limits
        },
    }



def walk_forward_portfolio_report(
    candles_by_ticker: dict[str, list[Candle]],
    folds: int = 4,
    warmup_bars: int = 200,
    config: BacktestConfig = BacktestConfig(),
    position_limits: tuple[int, ...] = (5, 7, 10),
) -> dict:
    """Build a multi-symbol portfolio from strictly chronological development folds.

    A common calendar timeline defines fold boundaries. Each ticker needs at least
    warmup_bars of its own observations before a fold starts. For a given fold,
    only candles strictly before its exclusive end boundary are passed to signal
    generation and backtesting. Signals must occur inside the fold and their next
    available entry candle must also be inside it. Any trade still open at the
    fold boundary is retained as OPEN and excluded by the portfolio simulator.

    The portfolio is flat at each fold boundary: positions are not carried across
    folds. This avoids leaking later bars into earlier folds and makes the
    concatenated closed-trade stream non-overlapping across folds, but is a
    conservative reset approximation rather than a fully continuous live system.
    """
    if folds < 2:
        raise ValueError("folds must be at least 2")
    if warmup_bars < 55:
        raise ValueError("warmup_bars must be >= 55")
    if not candles_by_ticker:
        raise ValueError("candles_by_ticker must not be empty")

    clean: dict[str, list[Candle]] = {}
    for ticker, rows in sorted(candles_by_ticker.items()):
        if not ticker or ticker.strip() != ticker:
            raise ValueError("ticker keys must be non-empty trimmed strings")
        clean[ticker] = validate_candles(rows)

    timeline = sorted({candle.timestamp for rows in clean.values() for candle in rows})
    available = len(timeline) - warmup_bars
    if available < folds * 2:
        raise ValueError("not enough common timeline observations for requested folds")
    fold_size = available // folds
    development_start_time = timeline[warmup_bars]

    # Separate continuous replay over the same development-only window.
    # Unlike the fold-isolated diagnostic below, exits may occur after a
    # walk-forward fold boundary. Signals remain causal and parameters frozen.
    continuous_candidates: list[PortfolioTrade] = []
    for ticker, rows in clean.items():
        signals = [
            signal for signal in generate_signals(rows)
            if rows[signal.index].timestamp >= development_start_time
            and signal.index + 1 < len(rows)
        ]
        for trade in backtest(rows, signals, config):
            if trade.signal_time >= development_start_time:
                continuous_candidates.append(PortfolioTrade(ticker, trade))

    from .regime import market_breadth_regime_report
    continuous_regime_analysis = market_breadth_regime_report(
        clean,
        [(item.ticker, item.trade) for item in continuous_candidates],
    )

    continuous_by_strategy = {}
    from .validation import CANDIDATE_SET_VERSION, REGISTERED_CANDIDATES
    for strategy in REGISTERED_CANDIDATES:
        selected = [
            item for item in continuous_candidates
            if item.trade.strategy == strategy
        ]
        continuous_by_strategy[strategy] = compare_position_limits(selected, position_limits)

    all_candidates: list[PortfolioTrade] = []
    fold_reports = []
    for fold_index in range(folds):
        start_index = warmup_bars + fold_index * fold_size
        end_index = (
            warmup_bars + (fold_index + 1) * fold_size
            if fold_index < folds - 1 else len(timeline)
        )
        start_time = timeline[start_index]
        end_exclusive = timeline[end_index] if end_index < len(timeline) else None
        fold_candidates: list[PortfolioTrade] = []
        eligible_tickers = 0
        skipped_short_history = 0
        signals_count = 0

        for ticker, rows in clean.items():
            history = [
                candle for candle in rows
                if end_exclusive is None or candle.timestamp < end_exclusive
            ]
            prior_bars = sum(candle.timestamp < start_time for candle in history)
            if prior_bars < warmup_bars:
                skipped_short_history += 1
                continue
            eligible_tickers += 1
            signals = generate_signals(history)
            fold_signals = [
                signal for signal in signals
                if history[signal.index].timestamp >= start_time
                and (end_exclusive is None or history[signal.index + 1].timestamp < end_exclusive)
            ]
            signals_count += len(fold_signals)
            ticker_trades = backtest(history, fold_signals, config)
            for trade in ticker_trades:
                if trade.signal_time < start_time:
                    continue
                if end_exclusive is not None and trade.entry_time >= end_exclusive:
                    continue
                fold_candidates.append(PortfolioTrade(ticker, trade))

        all_candidates.extend(fold_candidates)
        fold_reports.append({
            "fold": fold_index + 1,
            "start_inclusive": start_time.isoformat(),
            "end_exclusive": end_exclusive.isoformat() if end_exclusive else None,
            "eligible_tickers": eligible_tickers,
            "tickers_skipped_for_short_history": skipped_short_history,
            "signals": signals_count,
            "closed_trades": sum(
                item.trade.status == "CLOSED" for item in fold_candidates
            ),
            "open_trades_excluded_at_fold_boundary": sum(
                item.trade.status != "CLOSED" for item in fold_candidates
            ),
        })

    by_strategy = {}
    for strategy in REGISTERED_CANDIDATES:
        selected = [
            item for item in all_candidates
            if item.trade.strategy == strategy
        ]
        by_strategy[strategy] = compare_position_limits(selected, position_limits)

    return {
        "status": "DEVELOPMENT_WALK_FORWARD_PORTFOLIO",
        "candidate_set_version": CANDIDATE_SET_VERSION,
        "method": "common chronological folds; per-ticker indicator warm-up; signal and entry confined to each fold; fold-boundary reset to flat",
        "warmup_bars": warmup_bars,
        "folds": fold_reports,
        "combined": compare_position_limits(all_candidates, position_limits),
        "by_strategy": by_strategy,
        "candidate_trades": len(all_candidates),
        "continuous_development_replay": {
            "status": "DEVELOPMENT_CONTINUOUS_PORTFOLIO",
            "method": "same frozen candidates on development-only window; causal signal generation; positions may carry across fold boundaries; open terminal trades excluded",
            "development_start_inclusive": development_start_time.isoformat(),
            "development_end_inclusive": timeline[-1].isoformat(),
            "candidate_trades": len(continuous_candidates),
            "combined": compare_position_limits(continuous_candidates, position_limits),
            "by_strategy": continuous_by_strategy,
            "market_breadth_regime_analysis": continuous_regime_analysis,
            "warning": "Continuous development replay is not independent validation. It uses the full frozen development window for exit simulation and must not be interpreted as prospective holdout performance.",
        },
        "warning": "Development-only portfolio screening. Fold-isolated results reset to flat at fold boundaries; continuous_development_replay is reported separately. No independent holdout observations are used; results are not production approval or a live signal.",
    }
