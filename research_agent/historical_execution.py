"""Frozen-cost historical execution replay for development diagnostics only.

This module applies the existing core simulator to the pre-cutoff D1 history.
It is deliberately separate from the prospective holdout and signal ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from .core import BacktestConfig, Candle, backtest, generate_signals, validate_candles
from .historical_replay import DEFAULT_CUTOFF_EXCLUSIVE, DEFAULT_EXCLUDED_SYMBOLS


def _parse_rows(items: list[dict[str, Any]]) -> list[Candle]:
    rows = []
    for index, item in enumerate(items):
        try:
            timestamp = datetime.fromisoformat(str(item["timestamp"]).replace("Z", "+00:00"))
            values = [float(item[key]) for key in ("open", "high", "low", "close", "volume")]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid D1 candle at row {index}: {exc}") from exc
        rows.append(Candle(timestamp, *values))
    return validate_candles(rows)


def _trade_summary(trades: list[tuple[str, Any]]) -> dict[str, Any]:
    closed = [
        trade for _, trade in trades
        if trade.status == "CLOSED" and trade.net_return is not None
    ]
    opened = sum(trade.status == "OPEN" for _, trade in trades)
    values = [float(trade.net_return) for trade in closed]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trade_records": len(trades),
        "closed_trades": len(closed),
        "open_terminal_trades": opened,
        "win_rate": len(wins) / len(values) if values else None,
        "mean_net_return": mean(values) if values else None,
        "median_net_return": median(values) if values else None,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "profit_factor_infinite": bool(gross_profit) and not gross_loss,
        "sum_trade_returns_not_portfolio_return": sum(values),
    }


def _grouped_summary(trades: list[tuple[str, Any]], key_fn) -> dict[str, Any]:
    groups: dict[str, list[tuple[str, Any]]] = defaultdict(list)
    for symbol, trade in trades:
        groups[str(key_fn(symbol, trade))].append((symbol, trade))
    return {key: _trade_summary(groups[key]) for key in sorted(groups)}


def _serialize_trade_records(trades: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    """Return auditable individual trade rows with deterministic historical IDs."""
    records = []
    for symbol, trade in trades:
        direction = "LONG" if trade.direction > 0 else "SHORT"
        identity = "|".join((
            "HISTORICAL", "v1-frozen-2026-11-19", symbol, trade.strategy,
            direction, trade.signal_time.isoformat(), trade.entry_time.isoformat(),
        ))
        records.append({
            "trade_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            "data_origin": "HISTORICAL",
            "cohort_version": "v1-frozen-2026-11-19",
            "symbol": symbol,
            "strategy": trade.strategy,
            "direction": direction,
            "signal_time": trade.signal_time.isoformat(),
            "entry_time": trade.entry_time.isoformat(),
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "net_return": trade.net_return,
            "status": trade.status,
            "exit_reason": trade.exit_reason,
        })
    return records


def build_historical_execution(
    candles_report: dict[str, Any],
    *,
    cutoff_exclusive: str = DEFAULT_CUTOFF_EXCLUSIVE,
    excluded_symbols: dict[str, str] | None = None,
    source_run_id: int | None = None,
    config: BacktestConfig = BacktestConfig(),
) -> dict[str, Any]:
    """Simulate frozen signals with the repository's actual core execution engine."""
    try:
        cutoff = date.fromisoformat(cutoff_exclusive)
    except (TypeError, ValueError) as exc:
        raise ValueError("cutoff_exclusive must be an ISO date YYYY-MM-DD") from exc

    results = candles_report.get("results")
    if not isinstance(results, dict) or not results:
        raise ValueError("Candle report must contain a non-empty results mapping")

    excluded = dict(DEFAULT_EXCLUDED_SYMBOLS if excluded_symbols is None else excluded_symbols)
    all_trades: list[tuple[str, Any]] = []
    signal_count = 0
    symbols_used: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    signal_counts: dict[str, int] = defaultdict(int)

    for raw_symbol, frames in sorted(results.items()):
        symbol = str(raw_symbol).strip().upper()
        if symbol in excluded:
            skipped[symbol] = excluded[symbol]
            continue
        if not isinstance(frames, dict) or not isinstance(frames.get("D1"), dict):
            skipped[symbol] = "D1 frame is missing"
            continue
        d1 = frames["D1"]
        if d1.get("source") != "MOEX ISS TQBR history":
            skipped[symbol] = "Unexpected D1 source; expected native MOEX ISS TQBR history"
            continue
        if d1.get("status") != "OK" or not isinstance(d1.get("candles"), list):
            skipped[symbol] = f"D1 status is not OK: {d1.get('status')}"
            continue

        all_rows = _parse_rows(d1["candles"])
        rows = [row for row in all_rows if row.timestamp.date() < cutoff]
        if len(rows) < 56:
            skipped[symbol] = f"Insufficient pre-cutoff D1 history: {len(rows)} bars"
            continue
        rows = validate_candles(rows)
        signals = generate_signals(rows)
        signal_count += len(signals)
        for signal in signals:
            direction = "LONG" if signal.direction > 0 else "SHORT"
            signal_counts[f"{signal.strategy}|{direction}"] += 1

        trades = backtest(rows, signals, config)
        all_trades.extend((symbol, trade) for trade in trades)
        symbols_used[symbol] = {
            "d1_bars_used": len(rows),
            "first_date": rows[0].timestamp.date().isoformat(),
            "last_date": rows[-1].timestamp.date().isoformat(),
            "signals": len(signals),
            "trade_records": len(trades),
        }

    if not symbols_used:
        raise ValueError("No eligible symbols remained for historical execution replay")

    return {
        "status": "HISTORICAL_EXECUTION_REPLAY_NOT_PROSPECTIVE_EVIDENCE",
        "source_generated_at_utc": candles_report.get("generated_at_utc"),
        "source_run_id": source_run_id,
        "cohort_version": "v1-frozen-2026-11-19",
        "cutoff_exclusive": cutoff.isoformat(),
        "universe_size_used": len(symbols_used),
        "symbols": symbols_used,
        "skipped_symbols": skipped,
        "signal_count": signal_count,
        "signal_counts_by_strategy_direction": dict(sorted(signal_counts.items())),
        "execution_config": {
            "fee_per_side": config.fee_per_side,
            "slippage_per_side": config.slippage_per_side,
            "stop_pct": config.stop_pct,
            "target_pct": config.target_pct,
            "max_bars": config.max_bars,
        },
        "summary": _trade_summary(all_trades),
        "trade_records": _serialize_trade_records(all_trades),
        "by_direction": _grouped_summary(
            all_trades, lambda _symbol, trade: "LONG" if trade.direction > 0 else "SHORT"
        ),
        "by_strategy": _grouped_summary(
            all_trades, lambda _symbol, trade: trade.strategy
        ),
        "by_strategy_direction": _grouped_summary(
            all_trades,
            lambda _symbol, trade: f"{trade.strategy}|{'LONG' if trade.direction > 0 else 'SHORT'}",
        ),
        "by_exit_reason": _grouped_summary(
            all_trades, lambda _symbol, trade: trade.exit_reason
        ),
        "by_symbol": _grouped_summary(all_trades, lambda symbol, _trade: symbol),
        "methodology": {
            "signals": "Generated by frozen research_agent.core.generate_signals; no fitting or parameter changes",
            "execution": "Existing research_agent.core.backtest implementation",
            "entry": "Signal close then next available D1 open",
            "overlap": "Non-overlapping trades within each symbol/strategy stream; different strategies and symbols are simulated independently and may overlap",
            "fills": "Stop-first on same bar; stop gaps fill at open; target gaps fill at target; two-sided slippage and fees",
            "holdout": f"All D1 candles dated {cutoff.isoformat()} or later are excluded",
            "portfolio": "No combined portfolio, capital, position sizing, or allocation calculation",
            "h1": "Historical H1 confirmation is not reconstructed",
        },
        "limitations": [
            "Historical development diagnostics only; not prospective holdout evidence or a profitability claim.",
            "Trade streams across strategies and symbols overlap; aggregate sum of trade returns is not a portfolio return.",
            "No automatic corporate-action adjustment; known in-window unresolved corporate-action symbols must be excluded.",
            "OHLC bars cannot reveal intrabar price path; stop-first ordering is a conservative deterministic convention.",
            "No mark-to-market portfolio accounting or short-sale collateral model.",
        ],
        "safety": "Read-only calculations; no account, broker, order, position, sizing, capital, or live-trading access.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen-cost historical execution replay (development only)")
    parser.add_argument("--candles", required=True)
    parser.add_argument("--output", default="moex_edge_historical_execution.json")
    parser.add_argument("--cutoff-exclusive", default=DEFAULT_CUTOFF_EXCLUSIVE)
    parser.add_argument("--exclude-symbols", default="", help="Additional symbols to exclude; known in-window corporate actions are always excluded")
    parser.add_argument("--source-run-id", type=int, default=None)
    args = parser.parse_args()
    report = json.loads(Path(args.candles).read_text(encoding="utf-8"))
    excluded = dict(DEFAULT_EXCLUDED_SYMBOLS)
    for symbol in args.exclude_symbols.split(","):
        symbol = symbol.strip().upper()
        if symbol:
            excluded.setdefault(symbol, "Excluded by explicit command-line configuration")
    result = build_historical_execution(
        report,
        cutoff_exclusive=args.cutoff_exclusive,
        excluded_symbols=excluded,
        source_run_id=args.source_run_id,
    )
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    summary = result["summary"]
    print(
        f"Historical execution: signals={result['signal_count']}, "
        f"closed={summary['closed_trades']}, open={summary['open_terminal_trades']}, "
        f"cutoff<{result['cutoff_exclusive']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
