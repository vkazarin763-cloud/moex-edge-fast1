"""Read-only latest-signal scanner using native D1 candidates and H1 alignment.

This module consumes a validated multi-timeframe JSON artifact. It never
fetches market data, accesses accounts, or imports execution code.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .core import Candle, _ema, _wilder_atr, _wilder_rsi, validate_candles
from .multi_timeframe_validation import candle_end_utc

MOSCOW = ZoneInfo("Europe/Moscow")
STRATEGY_COHORT_VERSION = "v1-frozen-2026-11-19"
STRATEGIES = (
    "Donchian20",
    "EMA20x50",
    "RSI14Trend50",
    "MACD12x26",
    "Keltner20x2ATR",
)


def _parse_candles(items: list[dict], *, source: str) -> list[Candle]:
    rows = []
    for item in items:
        stamp = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            if not source.startswith("MOEX ISS"):
                raise ValueError("Timezone-naive timestamp from non-MOEX source")
            stamp = stamp.replace(tzinfo=MOSCOW)
        rows.append(Candle(
            stamp, float(item["open"]), float(item["high"]),
            float(item["low"]), float(item["close"]), float(item["volume"]),
        ))
    return validate_candles(rows)


def _latest_closed_index(candles: list[dict], source: str, frame: str,
                         cutoff: datetime) -> int | None:
    latest = None
    for index, item in enumerate(candles):
        end = candle_end_utc(item["timestamp"], source, frame)
        if end <= cutoff:
            latest = index
        else:
            break
    return latest


def _d1_signals_at_last_bar(rows: list[Candle]) -> list[dict]:
    """Evaluate the five frozen candidate formulas on the latest closed D1 bar."""
    rows = validate_candles(rows)
    i = len(rows) - 1
    # Match the frozen research warm-up: first eligible signal index is 55.
    if i < 55:
        return []
    closes = [row.close for row in rows]
    ema12, ema20, ema26, ema50 = (
        _ema(closes, 12), _ema(closes, 20), _ema(closes, 26), _ema(closes, 50)
    )
    macd = [fast - slow for fast, slow in zip(ema12, ema26)]
    macd_signal = _ema(macd, 9)
    rsi14 = _wilder_rsi(closes, 14)
    atr14 = _wilder_atr(rows, 14)
    prior_high = max(row.high for row in rows[i - 20:i])
    prior_low = min(row.low for row in rows[i - 20:i])
    upper = ema20[i] + 2.0 * atr14[i] if atr14[i] is not None else None
    lower = ema20[i] - 2.0 * atr14[i] if atr14[i] is not None else None
    prev_upper = ema20[i - 1] + 2.0 * atr14[i - 1] if atr14[i - 1] is not None else None
    prev_lower = ema20[i - 1] - 2.0 * atr14[i - 1] if atr14[i - 1] is not None else None
    close, previous_close = rows[i].close, rows[i - 1].close
    signals = []
    # Expose the exact closed-D1 values used by the frozen formulas. These are
    # diagnostics only; they do not alter the registered entry conditions.
    signal_parameters = {
        "close": close,
        "previous_close": previous_close,
        "donchian20_prior_high": prior_high,
        "donchian20_prior_low": prior_low,
        "ema20": ema20[i],
        "ema20_previous": ema20[i - 1],
        "ema50": ema50[i],
        "ema50_previous": ema50[i - 1],
        "rsi14": rsi14[i],
        "rsi14_previous": rsi14[i - 1],
        "macd12_26": macd[i],
        "macd_signal9": macd_signal[i],
        "macd12_26_previous": macd[i - 1],
        "macd_signal9_previous": macd_signal[i - 1],
        "atr14": atr14[i],
        "keltner20_upper_2atr": upper,
        "keltner20_lower_2atr": lower,
    }

    def add(strategy: str, direction: int):
        signals.append({
            "strategy": strategy,
            "direction": "LONG" if direction > 0 else "SHORT",
            "direction_code": direction,
            "signal_index": i,
            "parameters": signal_parameters,
        })

    if close > prior_high:
        add("Donchian20", 1)
    elif close < prior_low:
        add("Donchian20", -1)

    if ema20[i] > ema50[i] and ema20[i - 1] <= ema50[i - 1]:
        add("EMA20x50", 1)
    elif ema20[i] < ema50[i] and ema20[i - 1] >= ema50[i - 1]:
        add("EMA20x50", -1)

    if rsi14[i] is not None and rsi14[i - 1] is not None:
        if ema20[i] > ema50[i] and rsi14[i] > 50 and rsi14[i - 1] <= 50:
            add("RSI14Trend50", 1)
        elif ema20[i] < ema50[i] and rsi14[i] < 50 and rsi14[i - 1] >= 50:
            add("RSI14Trend50", -1)

    if macd[i] > macd_signal[i] and macd[i - 1] <= macd_signal[i - 1]:
        add("MACD12x26", 1)
    elif macd[i] < macd_signal[i] and macd[i - 1] >= macd_signal[i - 1]:
        add("MACD12x26", -1)

    if upper is not None and prev_upper is not None:
        if close > upper and previous_close <= prev_upper:
            add("Keltner20x2ATR", 1)
        elif close < lower and previous_close >= prev_lower:
            add("Keltner20x2ATR", -1)

    return signals


def _h1_alignment(rows: list[Candle], direction: int) -> dict:
    """Informational H1 trend confirmation; it does not filter D1 signals."""
    rows = validate_candles(rows)
    if len(rows) < 50:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "bars_available": len(rows),
            "required_bars": 50,
        }
    closes = [row.close for row in rows]
    ema20 = _ema(closes, 20)[-1]
    ema50 = _ema(closes, 50)[-1]
    last = rows[-1]
    if direction > 0:
        confirmed = ema20 > ema50 and last.close > ema20
    else:
        confirmed = ema20 < ema50 and last.close < ema20
    return {
        "status": "CONFIRMED" if confirmed else "NOT_CONFIRMED",
        "rule": "LONG: H1 EMA20 > EMA50 and close > EMA20; SHORT: H1 EMA20 < EMA50 and close < EMA20",
        "h1_close": last.close,
        "h1_ema20": ema20,
        "h1_ema50": ema50,
        "h1_timestamp": last.timestamp.isoformat(),
    }


def scan_multi_timeframe_report(candles_report: dict, validation_report: dict) -> dict:
    """Create latest D1 strategy signals and attach the latest causally aligned H1 state."""
    if validation_report.get("status") != "PASS" or validation_report.get("issue_count") != 0:
        raise ValueError("Input validation report must be PASS with zero issues")
    cutoff = datetime.fromisoformat(
        validation_report["as_of_utc"].replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    if candles_report.get("generated_at_utc") != validation_report.get("generated_at_utc"):
        raise ValueError("Candle and validation reports must have the same snapshot time")

    signals = []
    skipped = []
    for symbol in candles_report.get("universe", []):
        symbol_data = candles_report["results"].get(symbol, {})
        d1_item = symbol_data.get("D1", {})
        h1_item = symbol_data.get("H1", {})
        if d1_item.get("status") != "OK" or h1_item.get("status") != "OK":
            skipped.append({"symbol": symbol, "reason": "D1_OR_H1_UNAVAILABLE"})
            continue

        d1_candles = d1_item.get("candles", [])
        h1_candles = h1_item.get("candles", [])
        d1_idx = _latest_closed_index(d1_candles, d1_item["source"], "D1", cutoff)
        if d1_idx is None:
            skipped.append({"symbol": symbol, "reason": "NO_CLOSED_D1_BAR"})
            continue
        d1_rows = _parse_candles(
            d1_candles[:d1_idx + 1], source=d1_item["source"]
        )
        d1_bar = d1_candles[d1_idx]
        d1_end = candle_end_utc(d1_bar["timestamp"], d1_item["source"], "D1")

        # Select only H1 bars fully closed by both the snapshot cutoff and the
        # D1 signal bar's close. This prevents using later intraday information.
        eligible_h1 = [
            row for row in h1_candles
            if candle_end_utc(row["timestamp"], h1_item["source"], "H1") <= min(cutoff, d1_end)
        ]
        if len(eligible_h1) < 50:
            skipped.append({"symbol": symbol, "reason": "INSUFFICIENT_CLOSED_H1_HISTORY"})
            continue
        h1_rows = _parse_candles(eligible_h1, source=h1_item["source"])
        d1_candidates = _d1_signals_at_last_bar(d1_rows)
        for candidate in d1_candidates:
            direction = candidate["direction_code"]
            h1 = _h1_alignment(h1_rows, direction)
            if h1.get("status") != "INSUFFICIENT_HISTORY":
                h1_end = candle_end_utc(h1_rows[-1].timestamp.isoformat(), h1_item["source"], "H1")
                h1["h1_bar_end_utc"] = h1_end.isoformat()
                h1["h1_age_minutes_at_d1_close"] = round(
                    (d1_end - h1_end).total_seconds() / 60, 2
                )
            signals.append({
                "symbol": symbol,
                "direction": candidate["direction"],
                "strategy": candidate["strategy"],
                "d1_signal_timestamp": d1_bar["timestamp"],
                "d1_close": d1_bar["close"],
                "d1_bar_end_utc": d1_end.isoformat(),
                "h1_confirmation": h1["status"],
                "h1": h1,
            })

    # Mark, but never resolve or suppress, cross-strategy directional conflicts.
    directions_by_symbol = {}
    for signal in signals:
        directions_by_symbol.setdefault(signal["symbol"], set()).add(signal["direction"])
    for signal in signals:
        signal["cross_strategy_conflict"] = len(directions_by_symbol[signal["symbol"]]) > 1

    return {
        "status": "READ_ONLY_LATEST_SIGNAL_SCAN",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of_utc": cutoff.isoformat(),
        "universe_size": len(candles_report.get("universe", [])),
        "symbols_with_d1_h1_data": len(candles_report.get("universe", [])) - len(skipped),
        "signals_count": len(signals),
        "signals": signals,
        "skipped_symbols": skipped,
        "strategy_cohort_version": STRATEGY_COHORT_VERSION,
        "strategies": list(STRATEGIES),
        "methodology": {
            "signal_source": "Latest fully closed native MOEX ISS TQBR D1 candle",
            "confirmation_source": "Latest native Finam H1 candle closed no later than the D1 signal candle end",
            "h1_confirmation": "Informational alignment only: LONG requires H1 EMA20>EMA50 and close>EMA20; SHORT requires H1 EMA20<EMA50 and close<EMA20. It does not suppress or rank D1 signals.",
            "lookahead_policy": "Only bars whose native interval end is <= as_of are eligible; H1 is additionally bounded by the D1 signal bar end.",
            "strategy_policy": "Uses the five frozen candidate formulas and their fixed parameters; no optimization or strategy selection is performed.",
            "research_status": "Scanner prototype only. This output is not a backtest, profitability claim, or trade instruction. The H1 alignment rule is a new informational overlay and must not be used to retune the frozen cohort.",
            "execution_policy": "Read-only; no broker account, order, position, or execution endpoints.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only MOEX EDGE D1/H1 latest signal scanner")
    parser.add_argument("--candles", default="moex_edge_multi_timeframe_candles.json")
    parser.add_argument("--validation", default="moex_edge_multi_timeframe_validation.json")
    parser.add_argument("--output", default="moex_edge_mtf_signals.json")
    args = parser.parse_args()
    candles = json.loads(Path(args.candles).read_text(encoding="utf-8"))
    validation = json.loads(Path(args.validation).read_text(encoding="utf-8"))
    result = scan_multi_timeframe_report(candles, validation)
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"MTF scan complete: {result['signals_count']} signals; "
        f"{result['symbols_with_d1_h1_data']}/{result['universe_size']} symbols"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
