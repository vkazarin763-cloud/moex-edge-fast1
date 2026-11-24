"""Read-only one-year Finam D1 research for a broad pre-registered MOEX technical-analysis candidate set.

The requested interval ends strictly before the frozen 2026-11-20 holdout.
No account, portfolio, order, or execution endpoints are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .core import BacktestConfig, Candle, Trade, _wilder_atr, generate_expanded_signals, summarize, validate_candles
from .multi_timeframe import RefreshingFinamClient
from .direction_forecast import run_direction_forecast

TICKERS = (
    "AFKS", "AFLT", "ALRS", "BSPB", "CBOM", "CHMF", "CNRU", "DOMRF",
    "ENPG", "FLOT", "GAZP", "GMKN", "HEAD", "IRAO", "LKOH", "MAGN",
    "MDMG", "MOEX", "MTSS", "NLMK", "NVTK", "OZON", "PHOR", "PLZL",
    "POSI", "RAGR", "RENI", "ROSN", "RTKM", "RUAL", "SBER", "SBERP",
    "SNGS", "SNGSP", "SVCB", "T", "TATN", "TATNP", "TRNFP", "UGLD",
    "VKCO", "VTBR", "X5", "YDEX",
)
STRATEGIES = ("Donchian20", "EMA20x50", "RSI14Trend50", "MACD12x26", "ADX14Trend", "Keltner20x2ATR", "Bollinger20x2", "VolumeBreakout", "BreakoutRetest", "EngulfingTrend", "PinBarTrend", "SqueezeBreakout", "TrendMomentumConfirm", "TrendVolumeBreakout", "ADXDonchian", "CandleVolumeConfirm")
HOLDOUT_START = date(2026, 11, 20)
DATA_START = date(2025, 11, 20)
MOSCOW = ZoneInfo("Europe/Moscow")
BASE_CONFIG = BacktestConfig(0.001, 0.0005, None, None, None)  # 0.10% fee + 0.05% slippage per side; no fixed stop, target, or time exit. Chandelier Exit is used below.


def _dataset_hash(rows: list[Candle]) -> str:
    payload = [[c.timestamp.isoformat(), c.open, c.high, c.low, c.close, c.volume] for c in rows]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _chandelier_backtest(rows: list[Candle], signals, config: BacktestConfig):
    """ATR(14) x 3 Chandelier Exit; exit is signalled at close and filled next open."""
    atr = _wilder_atr(rows, 14)
    trades = []
    available_after = -1
    for signal in sorted(signals, key=lambda item: (item.index, -item.direction)):
        entry_index = signal.index + 1
        if signal.direction not in (-1, 1) or entry_index >= len(rows) or entry_index <= available_after:
            continue
        entry_fill = rows[entry_index].open * (1.0 + signal.direction * config.slippage_per_side)
        exit_index = None
        exit_fill = None
        for index in range(entry_index, len(rows) - 1):
            if atr[index] is None or index < 21:
                continue
            trailing = rows[index - 21:index + 1]
            if signal.direction == 1:
                chandelier = max(bar.high for bar in trailing) - 3.0 * atr[index]
                exit_triggered = rows[index].close <= chandelier
            else:
                chandelier = min(bar.low for bar in trailing) + 3.0 * atr[index]
                exit_triggered = rows[index].close >= chandelier
            if exit_triggered:
                exit_index = index + 1
                raw_exit = rows[exit_index].open
                exit_fill = raw_exit * (1.0 - signal.direction * config.slippage_per_side)
                break
        if exit_index is None:
            trades.append(Trade(
                signal.strategy, signal.direction, rows[signal.index].timestamp,
                rows[entry_index].timestamp, None, entry_fill, None, None,
                "OPEN", "END_OF_DATA",
            ))
            available_after = len(rows) - 1
            continue
        gross = signal.direction * (exit_fill - entry_fill) / entry_fill
        fee_cost = config.fee_per_side * (entry_fill + exit_fill) / entry_fill
        net_return = gross - fee_cost
        trades.append(Trade(
            signal.strategy, signal.direction, rows[signal.index].timestamp,
            rows[entry_index].timestamp, rows[exit_index].timestamp,
            entry_fill, exit_fill, net_return, "CLOSED", "CHANDELIER_EXIT",
        ))
        available_after = exit_index
    return trades


def _trades_for_window(rows: list[Candle], strategy: str, config: BacktestConfig,
                       start_index: int, end_index: int):
    if end_index - start_index < 2 or end_index <= 0:
        return []
    history = rows[:end_index]
    signals = [
        signal for signal in generate_expanded_signals(history)
        if signal.strategy == strategy and start_index <= signal.index < end_index - 1
    ]
    return _chandelier_backtest(history, signals, config)


def _aggregate(rows_by_ticker: dict[str, list[Candle]], strategy: str,
               config: BacktestConfig, window: str):
    trades = []
    per_ticker = {}
    for ticker, rows in sorted(rows_by_ticker.items()):
        if len(rows) < 60:
            per_ticker[ticker] = {"status": "INSUFFICIENT_BARS", "bars": len(rows)}
            continue
        if window == "all":
            start_index, end_index = 55, len(rows)
        else:
            split = max(56, len(rows) // 2)
            if window == "first_half":
                start_index, end_index = 55, split
            else:
                start_index, end_index = split, len(rows)
        selected = _trades_for_window(rows, strategy, config, start_index, end_index)
        trades.extend(selected)
        per_ticker[ticker] = {
            "status": "ANALYZED",
            "bars": len(rows),
            "trades": summarize(selected),
        }
    return {
        "pooled_trade_statistics_not_portfolio_return": summarize(trades),
        "tickers_analyzed": sum(v.get("status") == "ANALYZED" for v in per_ticker.values()),
        "tickers_insufficient": sum(v.get("status") != "ANALYZED" for v in per_ticker.values()),
        "per_ticker": per_ticker,
        "trade_ledger": [
            {
                "ticker": ticker,
                "strategy": trade.strategy,
                "direction": "LONG" if trade.direction == 1 else "SHORT",
                "signal_time": trade.signal_time.isoformat(),
                "entry_time": trade.entry_time.isoformat(),
                "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "net_return": trade.net_return,
                "status": trade.status,
                "exit_reason": trade.exit_reason,
            }
            for ticker, rows in sorted(rows_by_ticker.items())
            if len(rows) >= 60
            for trade in _trades_for_window(
                rows, strategy, config,
                55 if window in ("all", "first_half") else max(56, len(rows) // 2),
                len(rows) if window in ("all", "second_half") else max(56, len(rows) // 2),
            )
        ],
    }


def run(api_token: str, source_app_id: str | None = None) -> dict:
    if not api_token.strip():
        raise ValueError("FINAM_API_TOKEN is required")
    # Exactly 365 days; the exclusive end is before the frozen holdout begins.
    start = datetime.combine(DATA_START, time.min, tzinfo=timezone.utc)
    end = datetime.combine(HOLDOUT_START, time.min, tzinfo=timezone.utc)
    if end - start != timedelta(days=365):
        raise AssertionError("Finam D1 request must be exactly 365 days")
    client = RefreshingFinamClient(api_token, source_app_id)
    rows_by_ticker: dict[str, list[Candle]] = {}
    data_audit = {}
    fetch_errors = {}

    for ticker in TICKERS:
        try:
            bars = client.fetch_bars(f"{ticker}@MISX", "TIME_FRAME_D", start, end)
            # Validate the unfiltered source series first, so duplicates/order/OHLC errors cannot disappear.
            raw_candles = validate_candles([bar.as_candle() for bar in bars]) if bars else []
            retained = [
                bar for bar in bars
                if bar.is_data_snapshot is not True
                and bar.timestamp.astimezone(MOSCOW).date() < HOLDOUT_START
                and bar.timestamp.astimezone(MOSCOW).date() >= DATA_START
            ]
            candles = validate_candles([bar.as_candle() for bar in retained]) if retained else []
            rows_by_ticker[ticker] = candles
            data_audit[ticker] = {
                "raw_bars": len(raw_candles),
                "retained_completed_bars": len(candles),
                "snapshot_true_excluded": sum(bar.is_data_snapshot is True for bar in bars),
                "holdout_date_bars_excluded": sum(
                    bar.timestamp.astimezone(MOSCOW).date() >= HOLDOUT_START
                    for bar in bars if bar.is_data_snapshot is not True
                ),
                "snapshot_unknown_retained": sum(bar.is_data_snapshot is None for bar in retained),
                "first_bar": candles[0].timestamp.isoformat() if candles else None,
                "last_bar": candles[-1].timestamp.isoformat() if candles else None,
                "sha256": _dataset_hash(candles) if candles else None,
                "status": "OK" if len(candles) >= 60 else "INSUFFICIENT_HISTORY",
            }
        except Exception as exc:
            rows_by_ticker[ticker] = []
            fetch_errors[ticker] = str(exc)
            data_audit[ticker] = {"status": "FETCH_OR_VALIDATION_ERROR", "error": str(exc)}

    analyzed = {ticker: rows for ticker, rows in rows_by_ticker.items() if len(rows) >= 60}
    double_cost_config = replace(
        BASE_CONFIG,
        fee_per_side=BASE_CONFIG.fee_per_side * 2,
        slippage_per_side=BASE_CONFIG.slippage_per_side * 2,
    )
    results = {}
    for strategy in STRATEGIES:
        results[strategy] = {
            "baseline_execution": {
                "config": asdict(BASE_CONFIG),
                "all_period": _aggregate(analyzed, strategy, BASE_CONFIG, "all"),
                "first_half": _aggregate(analyzed, strategy, BASE_CONFIG, "first_half"),
                "second_half": _aggregate(analyzed, strategy, BASE_CONFIG, "second_half"),
            },
            "double_cost_stress": {
                "config": asdict(double_cost_config),
                "all_period": _aggregate(analyzed, strategy, double_cost_config, "all"),
                "first_half": _aggregate(analyzed, strategy, double_cost_config, "first_half"),
                "second_half": _aggregate(analyzed, strategy, double_cost_config, "second_half"),
            },
        }

    incomplete_symbols = [
        ticker for ticker in TICKERS
        if ticker not in fetch_errors and len(rows_by_ticker[ticker]) < 60
    ]
    report = {
        "report_version": "finam-ta-library-d1-v2",
        "status": "COMPLETE" if not fetch_errors and not incomplete_symbols else "INCOMPLETE_DATA",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Finam Trade API TIME_FRAME_D, native D1 bars",
        "universe": list(TICKERS),
        "universe_count": len(TICKERS),
        "requested_interval_utc": {
            "start_inclusive": start.isoformat(),
            "end_exclusive": end.isoformat(),
            "calendar_days": 365,
        },
        "development_cutoff": "2026-11-19 inclusive",
        "holdout_start": HOLDOUT_START.isoformat(),
        "holdout_policy": "Any provider-returned D1 bar with Moscow session date on or after 2026-11-20 is excluded before signal generation, indicators, trades, and performance metrics; boundary bars may be validated as source data but are never used in research.",
        "strategies": list(STRATEGIES),
        "execution_policy": {
            "baseline": asdict(BASE_CONFIG),
            "stress": asdict(double_cost_config),
            "entry": "Signal at completed D1 close; entry at next D1 open.",
            "exit_policy": "Chandelier Exit: rolling 22-bar high/low +/- 3 x Wilder ATR(14); trigger at completed D1 close and fill at next D1 open.",
            "position_overlap": "One open trade per ticker and strategy; strategies evaluated independently.",
            "fixed_stop_target_time_exit": "Disabled; no fixed stop, fixed target, or maximum holding period.",
            "terminal_open_trades": "Reported as OPEN and excluded from realized return statistics.",
            "portfolio_claims": "No portfolio return, capital, sizing, or drawdown is inferred from pooled trades.",
        },
        "data_summary": {
            "symbols_with_usable_history": len(analyzed),
            "symbols_insufficient_history": len(incomplete_symbols),
            "symbols_with_fetch_or_validation_errors": len(fetch_errors),
            "total_retained_bars": sum(len(rows) for rows in analyzed.values()),
            "errors": fetch_errors,
        },
        "data_audit": data_audit,
        "candles": {
            ticker: [
                {"timestamp": candle.timestamp.isoformat(), "open": candle.open,
                 "high": candle.high, "low": candle.low, "close": candle.close,
                 "volume": candle.volume}
                for candle in rows_by_ticker[ticker]
            ]
            for ticker in TICKERS
        },
        "results": results,
        "interpretation": (
            "One-year exploratory historical screen only. Half-period metrics are temporal diagnostics, "
            "not independent holdout evidence. Pooled trade statistics are not portfolio returns. "
            "No strategy is approved for live signals or trading by this report."
        ),
        "safety": "Read-only market-data calls; no broker accounts, orders, positions, or execution endpoints.",
    }
    # Reuse the exact validated Finam D1 candles; never fetch a second data source.
    report["direction_forecast_research"] = run_direction_forecast(rows_by_ticker, data_audit)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Finam D1 one-year technical-analysis research")
    parser.add_argument("--output", default="finam_two_strategy_report.json")
    args = parser.parse_args()
    token = os.environ.get("FINAM_API_TOKEN", "").strip()
    source_app_id = os.environ.get("FINAM_SOURCE_APP_ID", "").strip() or None
    report = run(token, source_app_id)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = report["data_summary"]
    forecast = report.get("direction_forecast_research", {})
    print(json.dumps({
        "direction_forecast_status": forecast.get("status"),
        "direction_forecast_source": forecast.get("source"),
        "direction_forecast_holdout_bars_used": forecast.get("holdout_bars_used"),
        "direction_forecast_horizons": {
            horizon: {
                "status": item.get("status"),
                "oos_samples": item.get("oos_samples"),
                "metrics": item.get("pooled_oos_metrics"),
            }
            for horizon, item in forecast.get("walk_forward", {}).items()
        },
    }, ensure_ascii=False))
    print(f"Status: {report['status']}")
    print(f"Finam D1 usable history: {summary['symbols_with_usable_history']}/{report['universe_count']} symbols")
    print(f"Retained bars: {summary['total_retained_bars']}")
    for strategy, item in report["results"].items():
        stats = item["baseline_execution"]["all_period"]["pooled_trade_statistics_not_portfolio_return"]
        print(f"{strategy}: {stats['closed_trades']} closed trades; win rate={stats['win_rate']}; avg net={stats['average_net_return']}; PF={stats['profit_factor']}")
    return 0 if report["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
