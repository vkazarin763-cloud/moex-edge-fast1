"""Historical, explicitly non-prospective replay of frozen D1 signal formulas.

This tool is for development diagnostics only. It never writes to the live signal
ledger, never changes the frozen cohort, and never accesses broker interfaces.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from .core import Candle, generate_signals, validate_candles
from .mtf_scanner import STRATEGY_COHORT_VERSION

DEFAULT_CUTOFF_EXCLUSIVE = "2026-11-20"
DEFAULT_EXCLUDED_SYMBOLS = {
    "GMKN": "Known 100-for-1 split effective 2024-04-04 falls inside the historical sample; OHLCV is not automatically adjusted.",
    "TRNFP": "Known 1-for-100 split effective 2024-02-21 falls inside the historical sample; OHLCV is not automatically adjusted.",
    "VTBR": "Known 5000-to-1 consolidation effective 2024-07-15 falls inside the historical sample; OHLCV is not automatically adjusted.",
    "PLZL": "Known 10-for-1 split effective 2025-03-27 falls inside the historical sample; OHLCV is not automatically adjusted.",
    "T": "Known 10-for-1 conversion effective 2026-04-17 falls inside the historical sample; OHLCV is not automatically adjusted.",
}
HORIZONS = (1, 5, 10, 20)


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _parse_d1_rows(items: list[dict[str, Any]]) -> list[Candle]:
    rows = []
    for index, item in enumerate(items):
        try:
            timestamp = datetime.fromisoformat(
                str(item["timestamp"]).replace("Z", "+00:00")
            )
            values = [float(item[key]) for key in ("open", "high", "low", "close", "volume")]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid D1 candle at row {index}: {exc}") from exc
        rows.append(Candle(timestamp, *values))
    return validate_candles(rows)


def _event_id(symbol: str, strategy: str, direction: int, timestamp: str) -> str:
    identity = "|".join((
        STRATEGY_COHORT_VERSION, symbol, strategy,
        "LONG" if direction > 0 else "SHORT", timestamp,
    ))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for strategy in ("Donchian20", "EMA20x50", "RSI14Trend50", "MACD12x26", "Keltner20x2ATR"):
        for direction in ("LONG", "SHORT"):
            subset = [
                event for event in events
                if event["strategy"] == strategy and event["direction"] == direction
            ]
            if not subset:
                continue
            item: dict[str, Any] = {"signals": len(subset)}
            for horizon in HORIZONS:
                values = [
                    event["outcomes"][str(horizon)]["directional_return_raw"]
                    for event in subset
                    if event["outcomes"][str(horizon)]["status"] == "MATURED"
                ]
                item[f"h{horizon}"] = {
                    "matured": len(values),
                    "pending": len(subset) - len(values),
                    "win_rate_raw": sum(value > 0 for value in values) / len(values) if values else None,
                    "mean_return_raw": mean(values) if values else None,
                    "median_return_raw": median(values) if values else None,
                    "p10_return_raw": _percentile(values, 0.10),
                    "p90_return_raw": _percentile(values, 0.90),
                }
            excursions = [
                event["mfe_mae_20"]
                for event in subset
                if event["mfe_mae_20"]["status"] == "MATURED"
            ]
            item["mfe_mae_20"] = {
                "matured": len(excursions),
                "pending": len(subset) - len(excursions),
                "mean_mfe_raw": mean(value["mfe_raw"] for value in excursions) if excursions else None,
                "mean_mae_raw": mean(value["mae_raw"] for value in excursions) if excursions else None,
            }
            result[f"{strategy}|{direction}"] = item
    return result


def build_historical_simulation(
    candles_report: dict[str, Any],
    *,
    cutoff_exclusive: str = DEFAULT_CUTOFF_EXCLUSIVE,
    excluded_symbols: dict[str, str] | None = None,
    source_run_id: int | None = None,
) -> dict[str, Any]:
    """Replay D1 signals and fixed-horizon outcomes strictly before the cutoff.

    The last retained D1 candle cannot itself generate an event because the
    frozen core requires a subsequent D1 open for entry. All outcome marks are
    calculated only from retained candles before cutoff_exclusive.
    """
    try:
        cutoff = date.fromisoformat(cutoff_exclusive)
    except (TypeError, ValueError) as exc:
        raise ValueError("cutoff_exclusive must be an ISO date YYYY-MM-DD") from exc

    results = candles_report.get("results")
    if not isinstance(results, dict) or not results:
        raise ValueError("Candle report must contain a non-empty results mapping")

    excluded = dict(DEFAULT_EXCLUDED_SYMBOLS if excluded_symbols is None else excluded_symbols)
    events: list[dict[str, Any]] = []
    symbols: dict[str, Any] = {}
    skipped: dict[str, str] = {}

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

        all_rows = _parse_d1_rows(d1["candles"])
        rows = [row for row in all_rows if row.timestamp.date() < cutoff]
        if len(rows) < 56:
            skipped[symbol] = f"Insufficient pre-cutoff D1 history: {len(rows)} bars"
            continue
        rows = validate_candles(rows)
        symbol_signals = generate_signals(rows)
        symbols[symbol] = {
            "d1_bars_used": len(rows),
            "first_date": rows[0].timestamp.date().isoformat(),
            "last_date": rows[-1].timestamp.date().isoformat(),
            "signal_count": len(symbol_signals),
        }

        for signal in symbol_signals:
            entry_index = signal.index + 1
            if entry_index >= len(rows):
                # Defensive guard; core.generate_signals currently excludes this case.
                continue
            entry = rows[entry_index].open
            signal_time = rows[signal.index].timestamp.isoformat()
            direction = "LONG" if signal.direction > 0 else "SHORT"
            outcomes: dict[str, Any] = {}
            for horizon in HORIZONS:
                mark_index = entry_index + horizon - 1
                if mark_index < len(rows):
                    mark = rows[mark_index]
                    directional_return = signal.direction * (mark.close - entry) / entry
                    outcomes[str(horizon)] = {
                        "status": "MATURED",
                        "mark_date": mark.timestamp.date().isoformat(),
                        "directional_return_raw": directional_return,
                    }
                else:
                    outcomes[str(horizon)] = {
                        "status": "PENDING",
                        "bars_available": max(0, len(rows) - entry_index),
                    }

            end_index = entry_index + 19
            if end_index < len(rows):
                window = rows[entry_index:end_index + 1]
                if signal.direction > 0:
                    mfe = (max(row.high for row in window) - entry) / entry
                    mae = (min(row.low for row in window) - entry) / entry
                else:
                    mfe = (entry - min(row.low for row in window)) / entry
                    mae = (entry - max(row.high for row in window)) / entry
                excursion = {
                    "status": "MATURED",
                    "end_date": rows[end_index].timestamp.date().isoformat(),
                    "mfe_raw": mfe,
                    "mae_raw": mae,
                }
            else:
                excursion = {
                    "status": "PENDING",
                    "bars_available": max(0, len(rows) - entry_index),
                }

            events.append({
                "event_id": _event_id(symbol, signal.strategy, signal.direction, signal_time),
                "symbol": symbol,
                "strategy": signal.strategy,
                "direction": direction,
                "signal_timestamp": signal_time,
                "entry_date": rows[entry_index].timestamp.date().isoformat(),
                "entry_open": entry,
                "h1_confirmation": "NOT_RECONSTRUCTED_HISTORICALLY",
                "outcomes": outcomes,
                "mfe_mae_20": excursion,
            })

    events.sort(key=lambda event: (
        event["signal_timestamp"], event["symbol"], event["strategy"], event["direction"]
    ))
    directions = {
        direction: sum(event["direction"] == direction for event in events)
        for direction in ("LONG", "SHORT")
    }
    strategies = {
        strategy: sum(event["strategy"] == strategy for event in events)
        for strategy in ("Donchian20", "EMA20x50", "RSI14Trend50", "MACD12x26", "Keltner20x2ATR")
    }
    return {
        "status": "HISTORICAL_DEVELOPMENT_SIMULATION_NOT_PROSPECTIVE_EVIDENCE",
        "source_generated_at_utc": candles_report.get("generated_at_utc"),
        "source_run_id": source_run_id,
        "cohort_version": STRATEGY_COHORT_VERSION,
        "cutoff_exclusive": cutoff.isoformat(),
        "universe_size_used": len(symbols),
        "symbols": symbols,
        "skipped_symbols": skipped,
        "signal_count": len(events),
        "direction_counts": directions,
        "strategy_counts": strategies,
        "summary_by_strategy_direction": _summarize(events),
        "events": events,
        "methodology": {
            "signal_formulas": "Frozen candidate formulas from research_agent.core.generate_signals; no fitting or parameter changes",
            "signal_warmup_bars": 55,
            "entry": "Next available D1 open after the signal close",
            "outcome_horizons": "1, 5, 10 and 20 subsequent valid D1 bars, counting the entry bar as bar 1",
            "returns": "Directional close-to-entry-open returns; raw/gross, excluding fees and slippage",
            "mfe_mae": "Directional favorable/adverse excursion over the first 20 D1 bars from entry, including the entry bar",
            "h1": "Historical H1 alignment is not reconstructed; the collector's H1 lookback is only 30 calendar days",
            "overlap": "Each signal is an independent observation; no portfolio or non-overlap constraint is applied",
            "holdout": f"All D1 candles dated {cutoff.isoformat()} or later are excluded",
            "corporate_actions": "No automatic price adjustment; symbols with known in-window unresolved corporate actions must be excluded explicitly",
        },
        "limitations": [
            "This is a development replay, not prospective evidence or a profitability claim.",
            "Gross directional returns omit transaction costs, execution effects, and portfolio constraints.",
            "Historical H1 confirmation is unavailable in the short-lookback H1 artifact.",
            "Signals overlap and are not independent statistical samples.",
            "Corporate-action price bases are not automatically adjusted.",
        ],
        "safety": "Read-only historical D1 calculations; no account, broker, order, position, sizing, or capital access.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a non-prospective historical MOEX EDGE signal replay")
    parser.add_argument("--candles", required=True, help="Validated multi-timeframe candle JSON artifact")
    parser.add_argument("--output", default="moex_edge_historical_simulation.json")
    parser.add_argument("--cutoff-exclusive", default=DEFAULT_CUTOFF_EXCLUSIVE)
    parser.add_argument("--exclude-symbols", default="T", help="Comma-separated symbols to exclude")
    parser.add_argument("--source-run-id", type=int, default=None)
    args = parser.parse_args()

    report = json.loads(Path(args.candles).read_text(encoding="utf-8"))
    excluded = {
        symbol.strip().upper(): DEFAULT_EXCLUDED_SYMBOLS.get(
            symbol.strip().upper(), "Excluded by explicit command-line configuration"
        )
        for symbol in args.exclude_symbols.split(",") if symbol.strip()
    }
    result = build_historical_simulation(
        report,
        cutoff_exclusive=args.cutoff_exclusive,
        excluded_symbols=excluded,
        source_run_id=args.source_run_id,
    )
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Historical simulation: signals={result['signal_count']}, "
        f"symbols={result['universe_size_used']}, skipped={len(result['skipped_symbols'])}, "
        f"cutoff<{result['cutoff_exclusive']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
