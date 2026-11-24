#!/usr/bin/env python3
"""Chronological event study of TA features on frozen MOEX OHLCV.

Only bars dated before 2026-11-20 are loaded into calculations. Signals are
observed at a completed close, entered at the next bar open, and exited at a
future close. This is an event study, not a portfolio/backtest engine.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_agent.technical_analysis_ready import (  # noqa: E402
    PATTERNS,
    _confirmed_pivots,
    _normalise_and_validate,
)

DATA_FILE = Path("frozen-data/moex_edge_multi_timeframe_candles.json")
VALIDATION_FILE = Path("frozen-data/moex_edge_multi_timeframe_validation.json")
EXPECTED_DATA_SHA256 = "8df302ac97b1132fefeae5054ec263ea3d2545f8a5622eef33065ee2fa2d5eee"
EXPECTED_VALIDATION_SHA256 = "900145ac5c01f80a0ba70535847737761509bfcae4c6a4b7fbb17c4d72646fb2"
CUTOFF = date(2026, 11, 20)
SPLIT = date(2026, 7, 1)
TIMEFRAMES = ("D1", "H1", "W1")
HORIZONS = (1, 3, 5, 10)
ROUND_TRIP_COST = 0.0016  # 0.08% each side
LEVEL_LOOKBACK = 250
PIVOT_LEFT = 3
PIVOT_RIGHT = 3
OUT = Path("ta-event-study-report")
OUT.mkdir(parents=True, exist_ok=True)

DIRECTIONAL_PATTERNS = {"engulfing", "hammer", "shootingstar", "morningstar", "eveningstar"}
NEUTRAL_PATTERNS = {"doji", "inside"}


def period_for(ts: pd.Timestamp) -> str:
    return "development" if ts.date() < SPLIT else "validation"


def channel_labels(high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int = 60) -> list[str | None]:
    """Causal OLS channel classification using each completed trailing window."""
    labels: list[str | None] = [None] * len(close)
    x = np.arange(window, dtype=float)
    xc = x - x.mean()
    denom = float(np.dot(xc, xc))
    for i in range(window - 1, len(close)):
        hs = high[i - window + 1:i + 1]
        ls = low[i - window + 1:i + 1]
        h_slope = float(np.dot(xc, hs - hs.mean()) / denom)
        l_slope = float(np.dot(xc, ls - ls.mean()) / denom)
        c = float(close[i])
        if c <= 0:
            continue
        gap = abs(h_slope - l_slope) / c
        mean_slope = (h_slope + l_slope) / (2.0 * c)
        if gap > 0.01:
            labels[i] = "DIVERGING_OR_UNSTABLE"
        elif mean_slope > 0.00005:
            labels[i] = "UP"
        elif mean_slope < -0.00005:
            labels[i] = "DOWN"
        else:
            labels[i] = "SIDEWAYS"
    return labels


def main() -> int:
    for path, expected in (
        (DATA_FILE, EXPECTED_DATA_SHA256),
        (VALIDATION_FILE, EXPECTED_VALIDATION_SHA256),
    ):
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Frozen input checksum mismatch for {path.name}: {actual}")

    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    validation = json.loads(VALIDATION_FILE.read_text(encoding="utf-8"))
    universe = payload.get("universe", [])
    if len(universe) != 44 or len(set(universe)) != 44:
        raise RuntimeError("Frozen universe is not exactly 44 unique symbols")
    if validation.get("status") != "PASS" or validation.get("symbol_count") != 44:
        raise RuntimeError("Frozen source validation did not PASS")

    events: list[dict] = []
    diagnostics: list[dict] = []
    errors: list[str] = []
    excluded = 0

    for symbol in universe:
        for timeframe in TIMEFRAMES:
            source = payload.get("results", {}).get(symbol, {}).get(timeframe)
            if not source or source.get("status") != "OK":
                errors.append(f"{symbol}/{timeframe}: source status missing/not OK")
                continue
            raw = pd.DataFrame(source.get("candles", []))
            if raw.empty:
                errors.append(f"{symbol}/{timeframe}: no candles")
                continue
            raw["timestamp"] = pd.to_datetime(raw["timestamp"], errors="raise")
            keep = raw["timestamp"].dt.date < CUTOFF
            excluded += int((~keep).sum())
            frame = _normalise_and_validate(raw.loc[keep, ["timestamp", "open", "high", "low", "close", "volume"]])
            n = len(frame)
            if n < 30:
                diagnostics.append({"symbol": symbol, "timeframe": timeframe, "bars": n, "status": "TOO_SHORT"})
                continue

            ta = frame[["open", "high", "low", "close", "volume"]].copy()
            ta.ta.ema(length=20, append=True)
            ta.ta.ema(length=50, append=True)
            ta.ta.ema(length=200, append=True)
            ta.ta.atr(length=14, append=True)
            pattern_frame = ta.ta.cdl_pattern(name=list(PATTERNS))
            if pattern_frame is None:
                pattern_frame = pd.DataFrame(index=ta.index)

            timestamps = frame["timestamp"].tolist()
            opens = frame["open"].to_numpy(dtype=float)
            highs = frame["high"].to_numpy(dtype=float)
            lows = frame["low"].to_numpy(dtype=float)
            closes = frame["close"].to_numpy(dtype=float)
            atr = ta.get("ATRr_14", pd.Series(np.nan, index=ta.index)).to_numpy(dtype=float)
            channels = channel_labels(highs, lows, closes)

            # Feature events are timestamped at the completed signal bar.
            features: dict[int, list[tuple[str, str, int]]] = defaultdict(list)
            for col in pattern_frame.columns:
                col_upper = str(col).upper()
                matched = next((p for p in PATTERNS if p.upper() in col_upper), None)
                if matched is None:
                    continue
                values = pd.to_numeric(pattern_frame[col], errors="coerce").fillna(0).to_numpy(dtype=float)
                for i, value in enumerate(values):
                    if value == 0:
                        continue
                    direction = 0 if matched in NEUTRAL_PATTERNS else (1 if value > 0 else -1)
                    features[i].append(("candlestick_pattern", matched.upper(), direction))

            # EMA stack is a descriptive trend condition, not an optimized entry rule.
            ema20 = ta.get("EMA_20", pd.Series(np.nan, index=ta.index)).to_numpy(dtype=float)
            ema50 = ta.get("EMA_50", pd.Series(np.nan, index=ta.index)).to_numpy(dtype=float)
            ema200 = ta.get("EMA_200", pd.Series(np.nan, index=ta.index)).to_numpy(dtype=float)
            for i in range(n):
                if np.isfinite([ema20[i], ema50[i], ema200[i]]).all():
                    if ema20[i] > ema50[i] > ema200[i]:
                        features[i].append(("ema_stack", "BULLISH_STACK", 1))
                    elif ema20[i] < ema50[i] < ema200[i]:
                        features[i].append(("ema_stack", "BEARISH_STACK", -1))

            # Only pivots with right-side confirmation at or before bar i are usable.
            pivots = _confirmed_pivots(frame, PIVOT_LEFT, PIVOT_RIGHT)
            pivots_by_confirmation: dict[int, list[dict]] = defaultdict(list)
            for pivot in pivots:
                pivots_by_confirmation[pivot["confirmed_index"]].append(pivot)
            confirmed: list[dict] = []
            for i in range(n):
                confirmed.extend(pivots_by_confirmation.get(i, []))
                confirmed = [p for p in confirmed if i - LEVEL_LOOKBACK < p["pivot_index"] <= i]
                current_atr = atr[i]
                if not np.isfinite(current_atr) or current_atr <= 0:
                    continue
                tolerance = max(0.5 * float(current_atr), closes[i] * 0.001)
                supports = [p for p in confirmed if p["kind"] == "support" and p["price"] <= closes[i]]
                resistances = [p for p in confirmed if p["kind"] == "resistance" and p["price"] >= closes[i]]
                if supports:
                    level = max(supports, key=lambda p: p["price"])
                    if closes[i] - level["price"] <= tolerance:
                        features[i].append(("pivot_level", "NEAR_CONFIRMED_SUPPORT", 1))
                if resistances:
                    level = min(resistances, key=lambda p: p["price"])
                    if level["price"] - closes[i] <= tolerance:
                        features[i].append(("pivot_level", "NEAR_CONFIRMED_RESISTANCE", -1))

            for i, channel in enumerate(channels):
                if channel == "UP":
                    features[i].append(("ols_channel", "UP", 1))
                elif channel == "DOWN":
                    features[i].append(("ols_channel", "DOWN", -1))
                elif channel == "SIDEWAYS":
                    features[i].append(("ols_channel", "SIDEWAYS", 0))

            # Baseline distribution is computed per symbol/timeframe/period/horizon/direction.
            baseline: dict[tuple, list[float]] = defaultdict(list)
            baseline_abs: dict[tuple, list[float]] = defaultdict(list)
            for i in range(n):
                p = period_for(timestamps[i])
                for h in HORIZONS:
                    exit_i = i + h
                    if exit_i >= n or i + 1 >= n:
                        continue
                    if timestamps[exit_i].date() >= CUTOFF or period_for(timestamps[exit_i]) != p:
                        continue
                    gross = closes[exit_i] / opens[i + 1] - 1.0
                    for direction in (-1, 1):
                        baseline[(p, h, direction)].append(direction * gross - ROUND_TRIP_COST)
                    baseline_abs[(p, h, 0)].append(abs(gross))

            # Each event is evaluated from next bar open to horizon close.
            for i, found in features.items():
                for feature, label, direction in found:
                    for h in HORIZONS:
                        exit_i = i + h
                        if exit_i >= n or i + 1 >= n:
                            continue
                        if timestamps[exit_i].date() >= CUTOFF:
                            continue
                        period = period_for(timestamps[i])
                        if period_for(timestamps[exit_i]) != period:
                            continue
                        gross = closes[exit_i] / opens[i + 1] - 1.0
                        if direction == 0:
                            value = abs(gross)
                            base_values = baseline_abs.get((period, h, 0), [])
                            baseline_value = float(np.mean(base_values)) if base_values else None
                            metric = "ABSOLUTE_MOVE"
                        else:
                            value = direction * gross - ROUND_TRIP_COST
                            base_values = baseline.get((period, h, direction), [])
                            baseline_value = float(np.mean(base_values)) if base_values else None
                            metric = "DIRECTIONAL_NET_RETURN"
                        events.append({
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "period": period,
                            "feature": feature,
                            "label": label,
                            "direction": "LONG" if direction > 0 else ("SHORT" if direction < 0 else "NEUTRAL"),
                            "metric": metric,
                            "horizon_bars": h,
                            "signal_timestamp": timestamps[i].isoformat(),
                            "entry_timestamp": timestamps[i + 1].isoformat(),
                            "exit_timestamp": timestamps[exit_i].isoformat(),
                            "event_value": value,
                            "matched_baseline": baseline_value,
                            "excess_vs_baseline": value - baseline_value if baseline_value is not None else None,
                        })

            diagnostics.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "bars_before_cutoff": n,
                "last_bar": timestamps[-1].isoformat(),
                "pattern_columns": len(pattern_frame.columns),
                "signal_bars": len(features),
                "status": "OK",
            })

    if errors:
        (OUT / "errors.json").write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError(f"Input processing errors: {len(errors)}; see errors.json")

    event_fields = list(events[0]) if events else []
    with (OUT / "events.csv").open("w", newline="", encoding="utf-8") as handle:
        if event_fields:
            writer = csv.DictWriter(handle, fieldnames=event_fields)
            writer.writeheader()
            writer.writerows(events)

    df = pd.DataFrame(events)
    summaries = []
    if not df.empty:
        group_cols = ["feature", "label", "direction", "metric", "timeframe", "horizon_bars", "period"]
        for keys, group in df.groupby(group_cols, dropna=False):
            values = group["event_value"].dropna()
            excess = group["excess_vs_baseline"].dropna()
            summaries.append({
                **dict(zip(group_cols, keys)),
                "events": int(len(group)),
                "symbols": int(group["symbol"].nunique()),
                "mean_event_value": float(values.mean()) if len(values) else None,
                "median_event_value": float(values.median()) if len(values) else None,
                "positive_event_rate": float((values > 0).mean()) if len(values) else None,
                "mean_matched_baseline": float(group["matched_baseline"].dropna().mean()) if group["matched_baseline"].notna().any() else None,
                "mean_excess_vs_baseline": float(excess.mean()) if len(excess) else None,
                "sample_flag": "LOW_SAMPLE_LT_30" if len(group) < 30 else "DESCRIPTIVE_SAMPLE",
            })
    with (OUT / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = list(summaries[0]) if summaries else []
        if fields:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(summaries)

    report = {
        "status": "PASS",
        "source_run_id": 44861047844,
        "source_artifact_id": 14690518588,
        "source_candles_sha256": EXPECTED_DATA_SHA256,
        "source_validation_sha256": EXPECTED_VALIDATION_SHA256,
        "holdout_cutoff_exclusive": CUTOFF.isoformat(),
        "holdout_bars_excluded": excluded,
        "development_period": f"before {SPLIT.isoformat()}",
        "validation_period": f"{SPLIT.isoformat()} through {date(2026, 11, 19).isoformat()}",
        "symbols": len(universe),
        "timeframes": list(TIMEFRAMES),
        "horizons_in_bars": list(HORIZONS),
        "round_trip_cost_assumption": ROUND_TRIP_COST,
        "entry_rule": "next bar open after signal bar close",
        "exit_rule": "close of bar signal_index + horizon",
        "features": ["candlestick_patterns", "confirmed_pivot_proximity", "OLS_channel", "EMA20_50_200_stack"],
        "event_count": len(events),
        "summary_rows": len(summaries),
        "series_processed": len(diagnostics),
        "series_errors": 0,
        "interpretation": "Exploratory event study only; overlapping events, no portfolio simulation, no statistical significance or profitability claim.",
        "diagnostics": diagnostics,
    }
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "diagnostics"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
