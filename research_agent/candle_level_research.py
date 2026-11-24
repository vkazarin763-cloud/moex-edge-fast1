"""Three-year, read-only MOEX D1 candlestick/level research with a bounded Finam H1 check.

D1 input uses public MOEX ISS per-security TQBR total-session daily history,
not raw calendar-date candles. H1 confirmation is fetched from Finam for the
exact 30-day window ending at the frozen holdout boundary. No broker/execution
endpoints are used.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .core import (
    BacktestConfig, Candle, Signal, _ema, summarize, validate_candles,
)
from .finam_market_data import FinamBar
from .finam_strategy_backtest import _chandelier_backtest
from .moex_iss import fetch_history_records
from .session_mapping import build_trading_day_candles
from .corporate_actions import apply_post_event_price_basis
from .multi_timeframe import RefreshingFinamClient

TICKERS = (
    "AFKS", "AFLT", "ALRS", "BSPB", "CBOM", "CHMF", "CNRU", "DOMRF",
    "ENPG", "FLOT", "GAZP", "GMKN", "HEAD", "IRAO", "LKOH", "MAGN",
    "MDMG", "MOEX", "MTSS", "NLMK", "NVTK", "OZON", "PHOR", "PLZL",
    "POSI", "RAGR", "RENI", "ROSN", "RTKM", "RUAL", "SBER", "SBERP",
    "SNGS", "SNGSP", "SVCB", "T", "TATN", "TATNP", "TRNFP", "UGLD",
    "VKCO", "VTBR", "X5", "YDEX",
)
DATA_START = date(2023, 11, 20)
HOLDOUT_START = date(2026, 11, 20)
RECENT_START = date(2026, 10, 22)
MOSCOW = ZoneInfo("Europe/Moscow")
H1_START_UTC = datetime(2026, 10, 20, 21, tzinfo=timezone.utc)
H1_END_UTC = datetime(2026, 11, 19, 21, tzinfo=timezone.utc)
CONFIG = BacktestConfig(
    fee_per_side=0.001, slippage_per_side=0.0005,
    stop_pct=None, target_pct=None, max_bars=None,
)
STRATEGIES = (
    "Engulfing", "PinBar", "InsideBarBreakout", "MorningStar",
    "EveningStar", "ThreeWhiteSoldiers", "ThreeBlackCrows",
    "DojiBreakout", "LevelBreakout", "FalseBreakout", "LevelRetest",
)


def _body(c: Candle) -> float:
    return abs(c.close - c.open)


def detect_signals(rows: list[Candle]) -> tuple[dict[str, list[Signal]], dict]:
    """Detect completed-bar candle patterns and causal pivot-level events.

    A swing pivot becomes usable only after three right-hand bars have closed.
    No pivot or level is backfilled into earlier bars.
    """
    rows = validate_candles(rows)
    found = {name: [] for name in STRATEGIES}
    level_audit = {"confirmed_resistance_pivots": 0, "confirmed_support_pivots": 0}
    highs: list[tuple[int, float]] = []  # (confirmation index, price)
    lows: list[tuple[int, float]] = []
    pending_retests: list[dict] = []

    for i in range(3, len(rows) - 1):
        c, p = rows[i], rows[i - 1]
        body, prev_body = _body(c), _body(p)
        span = c.high - c.low
        # Two-candle engulfing.
        if prev_body > 0 and body > 0:
            if p.close < p.open and c.close > c.open and c.open <= p.close and c.close >= p.open:
                found["Engulfing"].append(Signal(i, 1, "Engulfing"))
            elif p.close > p.open and c.close < c.open and c.open >= p.close and c.close <= p.open:
                found["Engulfing"].append(Signal(i, -1, "Engulfing"))

        # Pin bars: wick at least twice the body, with close in the outer 35%.
        if span > 0:
            lower = min(c.open, c.close) - c.low
            upper = c.high - max(c.open, c.close)
            if lower >= 2 * max(body, span * 0.03) and (c.high - c.close) / span <= 0.35:
                found["PinBar"].append(Signal(i, 1, "PinBar"))
            elif upper >= 2 * max(body, span * 0.03) and (c.close - c.low) / span <= 0.35:
                found["PinBar"].append(Signal(i, -1, "PinBar"))

        # Inside-bar range break: the previous bar was inside its mother bar.
        if i >= 2:
            mother, inside = rows[i - 2], p
            if inside.high < mother.high and inside.low > mother.low:
                if c.close > mother.high:
                    found["InsideBarBreakout"].append(Signal(i, 1, "InsideBarBreakout"))
                elif c.close < mother.low:
                    found["InsideBarBreakout"].append(Signal(i, -1, "InsideBarBreakout"))

        # Three-candle stars; no overnight gap assumption (MOEX equities often gap).
        if i >= 2:
            a, b = rows[i - 2], p
            if _body(a) >= 0.55 * (a.high - a.low) and _body(b) <= 0.35 * max(_body(a), 1e-12):
                midpoint_a = (a.open + a.close) / 2
                if a.close < a.open and c.close > c.open and c.close > midpoint_a:
                    found["MorningStar"].append(Signal(i, 1, "MorningStar"))
                elif a.close > a.open and c.close < c.open and c.close < midpoint_a:
                    found["EveningStar"].append(Signal(i, -1, "EveningStar"))

        # Three advancing/declining candles with progressively stronger closes.
        if i >= 2:
            a, b = rows[i - 2], p
            if (a.close > a.open and b.close > b.open and c.close > c.open
                    and a.close < b.close < c.close
                    and min(_body(a), _body(b), body) > 0):
                found["ThreeWhiteSoldiers"].append(Signal(i, 1, "ThreeWhiteSoldiers"))
            elif (a.close < a.open and b.close < b.open and c.close < c.open
                    and a.close > b.close > c.close
                    and min(_body(a), _body(b), body) > 0):
                found["ThreeBlackCrows"].append(Signal(i, -1, "ThreeBlackCrows"))

        # Doji followed by a confirmed break of the doji range.
        if i >= 2:
            doji = p
            doji_range = doji.high - doji.low
            if doji_range > 0 and _body(doji) <= 0.10 * doji_range:
                if c.close > doji.high:
                    found["DojiBreakout"].append(Signal(i, 1, "DojiBreakout"))
                elif c.close < doji.low:
                    found["DojiBreakout"].append(Signal(i, -1, "DojiBreakout"))

        # Expire old levels and pending retests before testing this completed bar.
        highs = [(known, price) for known, price in highs if i - known <= 120]
        lows = [(known, price) for known, price in lows if i - known <= 120]
        pending_retests = [item for item in pending_retests if i - item["index"] <= 10]

        # Use only previously confirmed pivot levels, with an ATR-independent
        # 0.25% buffer to keep the rule fixed across all securities.
        resistance_candidates = [price for _, price in highs if price > p.close]
        support_candidates = [price for _, price in lows if price < p.close]
        resistance = min(resistance_candidates) if resistance_candidates else None
        support = max(support_candidates) if support_candidates else None
        if resistance is not None:
            if c.close > resistance * 1.0025 and p.close <= resistance:
                found["LevelBreakout"].append(Signal(i, 1, "LevelBreakout"))
                pending_retests.append({"index": i, "price": resistance, "direction": 1})
            elif c.high > resistance * 1.0025 and c.close < resistance:
                found["FalseBreakout"].append(Signal(i, -1, "FalseBreakout"))
        if support is not None:
            if c.close < support * 0.9975 and p.close >= support:
                found["LevelBreakout"].append(Signal(i, -1, "LevelBreakout"))
                pending_retests.append({"index": i, "price": support, "direction": -1})
            elif c.low < support * 0.9975 and c.close > support:
                found["FalseBreakout"].append(Signal(i, 1, "FalseBreakout"))

        for item in pending_retests:
            level, direction = item["price"], item["direction"]
            if i > item["index"] and direction == 1 and c.low <= level * 1.005 and c.close > level:
                found["LevelRetest"].append(Signal(i, 1, "LevelRetest"))
                item["done"] = True
            elif i > item["index"] and direction == -1 and c.high >= level * 0.995 and c.close < level:
                found["LevelRetest"].append(Signal(i, -1, "LevelRetest"))
                item["done"] = True
        pending_retests = [item for item in pending_retests if not item.get("done")]

        # Confirm a pivot at i only after all three right-hand bars exist.
        pivot = i - 3
        if pivot >= 3:
            candidate = rows[pivot]
            left = rows[pivot - 3:pivot]
            right = rows[pivot + 1:i + 1]
            if candidate.high > max(bar.high for bar in left + right):
                highs.append((i, candidate.high))
                level_audit["confirmed_resistance_pivots"] += 1
            if candidate.low < min(bar.low for bar in left + right):
                lows.append((i, candidate.low))
                level_audit["confirmed_support_pivots"] += 1

    return found, level_audit


def _fetch_d1_model_rows(ticker: str, start_text: str, end_text: str):
    """Load history-backed TQBR trading-day bars and isolate share-price bases."""
    history_records = fetch_history_records(
        ticker, start_text, end_text, board="TQBR"
    )
    rows, session_audit = build_trading_day_candles(
        history_records, DATA_START, HOLDOUT_START - timedelta(days=1)
    )
    rows, corporate_action_audit = apply_post_event_price_basis(
        ticker, rows, minimum_development_bars=200
    )
    audit = {
        "history_rows": len(history_records),
        "session_mapping": session_audit,
        "corporate_action_price_basis": corporate_action_audit,
    }
    if corporate_action_audit.get("status") == "INSUFFICIENT_POST_ACTION_HISTORY":
        audit["status"] = "INSUFFICIENT_POST_ACTION_HISTORY"
        return [], audit
    if not rows:
        raise ValueError("No eligible post-action TQBR D1 rows remain")
    audit["status"] = "OK"
    return rows, audit


def _h1_daily_trend(bars: list[FinamBar]) -> dict[date, int]:
    """Map each Moscow session date to its last available completed H1 EMA trend."""
    usable = [
        bar for bar in bars
        if bar.is_data_snapshot is not True
        and bar.timestamp + timedelta(hours=1) <= H1_END_UTC
        and bar.timestamp.astimezone(MOSCOW).date() < HOLDOUT_START
    ]
    if not usable:
        return {}
    candles = validate_candles([bar.as_candle() for bar in usable])
    closes = [bar.close for bar in candles]
    fast, slow = _ema(closes, 20), _ema(closes, 50)
    result = {}
    for i, bar in enumerate(candles):
        if i >= 49:
            result[bar.timestamp.astimezone(MOSCOW).date()] = 1 if fast[i] > slow[i] else -1
    return result


def _run_backtest(rows: list[Candle], signals: list[Signal]):
    return _chandelier_backtest(rows, signals, CONFIG)


def run(api_token: str, source_app_id: str | None = None) -> dict:
    if not api_token.strip():
        raise ValueError("FINAM_API_TOKEN is required for the bounded H1 check")
    start_text, end_text = DATA_START.isoformat(), (HOLDOUT_START - timedelta(days=1)).isoformat()
    client = RefreshingFinamClient(api_token, source_app_id)
    data, h1_trends, errors = {}, {}, {}
    audit = {}

    for ticker in TICKERS:
        try:
            rows, source_audit = _fetch_d1_model_rows(ticker, start_text, end_text)
            if not rows:
                data[ticker] = []
                audit[ticker] = {
                    **source_audit,
                    "bars": 0,
                    "status": source_audit.get("status", "INSUFFICIENT_HISTORY"),
                    "holdout_bars_used": 0,
                }
                continue
            rows = validate_candles(rows)
            data[ticker] = rows
            audit[ticker] = {
                **source_audit,
                "status": "OK", "bars": len(rows),
                "first_date": rows[0].timestamp.date().isoformat(),
                "last_date": rows[-1].timestamp.date().isoformat(),
                "calendar_history_days": (rows[-1].timestamp.date() - rows[0].timestamp.date()).days,
                "full_three_year_coverage": rows[0].timestamp.date() <= DATA_START + timedelta(days=7),
                "holdout_bars_used": 0,
            }
        except Exception as exc:
            data[ticker] = []
            errors[ticker] = f"D1: {exc}"
            audit[ticker] = {"status": "D1_ERROR", "error": str(exc)}

    h1_audit = {}
    for ticker in TICKERS:
        try:
            bars = client.fetch_bars(
                f"{ticker}@MISX", "TIME_FRAME_H1", H1_START_UTC, H1_END_UTC
            )
            usable = [
                bar for bar in bars
                if bar.is_data_snapshot is not True
                and bar.timestamp + timedelta(hours=1) <= H1_END_UTC
                and bar.timestamp.astimezone(MOSCOW).date() < HOLDOUT_START
            ]
            h1_trends[ticker] = _h1_daily_trend(usable)
            h1_audit[ticker] = {
                "status": "OK" if h1_trends[ticker] else "NO_COMPLETED_H1",
                "raw_bars": len(bars), "completed_pre_holdout_bars": len(usable),
                "trend_dates": len(h1_trends[ticker]),
            }
        except Exception as exc:
            h1_trends[ticker] = {}
            h1_audit[ticker] = {"status": "ERROR", "error": str(exc)}
            errors[ticker] = (errors.get(ticker, "") + f" H1: {exc}").strip()

    aggregate = {
        name: {"signals": 0, "all_period_trades": [], "all_period_tickers": set(), "recent_signals": 0,
               "recent_trades": [], "recent_tickers": set(), "h1_covered": 0, "h1_confirmed": 0,
               "h1_confirmed_trades": [], "h1_confirmed_tickers": set()}
        for name in STRATEGIES
    }
    per_ticker = {}
    for ticker, rows in data.items():
        if not rows:
            continue
        signals_by_strategy, level_audit = detect_signals(rows)
        per_ticker[ticker] = {"bars": len(rows), "levels": level_audit, "strategies": {}}
        trend_by_day = h1_trends.get(ticker, {})
        for name, signals in signals_by_strategy.items():
            recent = [
                signal for signal in signals
                if RECENT_START <= rows[signal.index].timestamp.date() < HOLDOUT_START
            ]
            confirmed = [
                signal for signal in recent
                if rows[signal.index].timestamp.date() in trend_by_day
                and trend_by_day[rows[signal.index].timestamp.date()] == signal.direction
            ]
            all_trades = _run_backtest(rows, signals)
            recent_trades = _run_backtest(rows, recent)
            confirmed_trades = _run_backtest(rows, confirmed)
            stats = summarize(all_trades)
            recent_stats = summarize(recent_trades)
            confirmed_stats = summarize(confirmed_trades)
            per_ticker[ticker]["strategies"][name] = {
                "signal_count": len(signals), "all_period": stats,
                "recent_30d_signal_count": len(recent),
                "recent_30d_unfiltered": recent_stats,
                "recent_30d_h1_confirmed_signal_count": len(confirmed),
                "recent_30d_h1_confirmed": confirmed_stats,
            }
            item = aggregate[name]
            item["signals"] += len(signals)
            item["all_period_trades"].extend(all_trades)
            if all_trades:
                item["all_period_tickers"].add(ticker)
            item["recent_signals"] += len(recent)
            item["recent_trades"].extend(recent_trades)
            if recent_trades:
                item["recent_tickers"].add(ticker)
            item["h1_covered"] += sum(
                rows[s.index].timestamp.date() in trend_by_day for s in recent
            )
            item["h1_confirmed"] += len(confirmed)
            item["h1_confirmed_trades"].extend(confirmed_trades)
            if confirmed_trades:
                item["h1_confirmed_tickers"].add(ticker)

    results = {}
    for name, item in aggregate.items():
        def merge_stats(trades, ticker_count):
            return {**summarize(trades), "tickers_with_trades": ticker_count}
        results[name] = {
            "total_signals": item["signals"],
            "all_period": merge_stats(item["all_period_trades"], len(item["all_period_tickers"])),
            "recent_30d_signals": item["recent_signals"],
            "recent_30d_unfiltered": merge_stats(item["recent_trades"], len(item["recent_tickers"])),
            "recent_30d_h1_coverage_signals": item["h1_covered"],
            "recent_30d_h1_confirmed_signals": item["h1_confirmed"],
            "recent_30d_h1_confirmed": merge_stats(item["h1_confirmed_trades"], len(item["h1_confirmed_tickers"])),
        }

    return {
        "report_version": "moex-candle-level-d1-3y-v1",
        "status": (
            "COMPLETE"
            if not errors and all(bool(rows) for rows in data.values())
            else "PARTIAL"
        ),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "universe": list(TICKERS), "universe_count": len(TICKERS),
        "d1_source": "MOEX ISS per-security TQBR total-session daily history (TRADEDATE); weekend sessions are included in the next ordinary trading day",
        "d1_period": {"start_inclusive": DATA_START.isoformat(),
                      "end_exclusive": HOLDOUT_START.isoformat(),
                      "holdout_start": HOLDOUT_START.isoformat()},
        "h1_source": "Finam TIME_FRAME_H1; exactly 30-day request ending before frozen holdout",
        "h1_period_utc": {"start_inclusive": H1_START_UTC.isoformat(),
                          "end_exclusive": H1_END_UTC.isoformat()},
        "execution": {
            "entry": "Signal on completed D1 close; next D1 open",
            "exit": "Chandelier Exit: rolling 22-bar high/low +/- 3 x Wilder ATR(14); trigger on completed D1 close, fill next D1 open",
            "costs": asdict(CONFIG),
            "fixed_stop_target_time_exit": "Disabled",
            "open_terminal_trades": "Excluded from realized return statistics",
            "portfolio_claims": "No portfolio return, sizing, capital or drawdown inferred",
        },
        "strategies": list(STRATEGIES),
        "level_method": "Confirmed 3-left/3-right swing pivots; usable only after three right bars close; levels expire after 120 D1 bars; breakout/false-breakout buffer 0.25%; retest window 10 bars.",
        "candle_pattern_definitions": {
            "Engulfing": "Two-candle body engulfing, bullish/bearish.",
            "PinBar": "Dominant rejection wick at least 2x body; close in outer 35% of range.",
            "InsideBarBreakout": "Close breaks the mother bar after a completed inside bar.",
            "MorningStar/EveningStar": "Three-bar reversal; middle body <=35% of first body; no overnight gap assumption.",
            "ThreeWhiteSoldiers/ThreeBlackCrows": "Three consecutive same-color candles with progressive closes.",
            "DojiBreakout": "Doji body <=10% of range, followed by close outside doji range.",
        },
        "data_summary": {
            "d1_symbols_ok": sum(bool(rows) for rows in data.values()),
            "d1_symbols_failed": sum(not rows for rows in data.values()),
            "d1_symbols_full_3y": sum(bool(rows) and audit[ticker].get("full_three_year_coverage", False) for ticker, rows in data.items()),
            "d1_symbols_shorter_history": sum(bool(rows) and not audit[ticker].get("full_three_year_coverage", False) for ticker, rows in data.items()),
            "d1_bars": sum(len(rows) for rows in data.values()),
            "h1_symbols_with_trend": sum(bool(v) for v in h1_trends.values()),
            "errors": errors,
        },
        "d1_audit": audit, "h1_audit": h1_audit,
        "results": results, "per_ticker": per_ticker,
        "interpretation": "Exploratory research only. Three-year D1 pattern/level results and a separate pre-holdout 30-day H1 confirmation diagnostic. No strategy is approved for live signals or trading.",
        "safety": "Read-only public market-data calls; no broker accounts, orders, positions, or execution endpoints. The 2026-11-20+ holdout is excluded.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="MOEX three-year candle and level research")
    parser.add_argument("--output", default="moex_candle_level_research_report.json")
    args = parser.parse_args()
    report = run(
        os.environ.get("FINAM_API_TOKEN", "").strip(),
        os.environ.get("FINAM_SOURCE_APP_ID", "").strip() or None,
    )
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "d1_symbols_ok": report["data_summary"]["d1_symbols_ok"],
        "d1_bars": report["data_summary"]["d1_bars"],
        "h1_symbols_with_trend": report["data_summary"]["h1_symbols_with_trend"],
        "errors": len(report["data_summary"]["errors"]),
        "output": args.output,
    }, ensure_ascii=False))
    return 0 if report["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
