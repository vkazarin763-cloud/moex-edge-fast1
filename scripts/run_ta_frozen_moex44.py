#!/usr/bin/env python3
"""Run the isolated TA adapter against the frozen MOEX 44 OHLCV artifact.

Bars dated 2026-11-20 or later are excluded before any analysis.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

from research_agent.technical_analysis_ready import analyze_ohlcv, _normalise_and_validate

ARTIFACT = Path("frozen-data/moex-edge-multi-timeframe-candles.zip")
EXPECTED_SHA256 = "6a9ee767f37bec1f9fa9d40d0868ccc8f36b2271dd5ef4a1715f83e4a51af137"
CUTOFF = date(2026, 11, 20)
TIMEFRAMES = ("D1", "H1", "W1")
OUT = Path("ta-real-data-report")
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    digest = hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RuntimeError(f"Frozen artifact SHA256 mismatch: {digest}")

    with zipfile.ZipFile(ARTIFACT) as archive:
        payload = json.loads(archive.read("moex_edge_multi_timeframe_candles.json"))
        validation = json.loads(archive.read("moex_edge_multi_timeframe_validation.json"))

    universe = payload.get("universe", [])
    if len(universe) != 44 or len(set(universe)) != 44:
        raise RuntimeError(f"Expected 44 unique tickers, got {len(universe)} / {len(set(universe))}")
    if validation.get("status") != "PASS" or validation.get("symbol_count") != 44:
        raise RuntimeError("Frozen source validation report is not PASS for 44 symbols")

    reports = []
    summary = []
    errors = []
    excluded_holdout_bars = 0

    for symbol in universe:
        symbol_data = payload["results"].get(symbol)
        if symbol_data is None:
            errors.append(f"{symbol}: missing from results")
            continue
        for timeframe in TIMEFRAMES:
            frame_data = symbol_data.get(timeframe)
            if not frame_data or frame_data.get("status") != "OK":
                errors.append(f"{symbol}/{timeframe}: missing or non-OK timeframe")
                continue
            raw = frame_data.get("candles", [])
            if not raw:
                errors.append(f"{symbol}/{timeframe}: empty candles")
                continue

            original = pd.DataFrame(raw)
            original["timestamp"] = pd.to_datetime(original["timestamp"], errors="raise")
            keep = original["timestamp"].dt.date < CUTOFF
            excluded_holdout_bars += int((~keep).sum())
            candles = original.loc[keep, ["timestamp", "open", "high", "low", "close", "volume"]].copy()
            if candles.empty:
                errors.append(f"{symbol}/{timeframe}: no pre-holdout bars")
                continue
            if not (candles["timestamp"].dt.date < CUTOFF).all():
                errors.append(f"{symbol}/{timeframe}: holdout leakage")
                continue

            try:
                validated = _normalise_and_validate(candles)
                result = analyze_ohlcv(validated)
            except Exception as exc:
                errors.append(f"{symbol}/{timeframe}: {type(exc).__name__}: {exc}")
                continue

            if result["last_completed_bar"][:10] >= CUTOFF.isoformat():
                errors.append(f"{symbol}/{timeframe}: latest analyzed bar crosses holdout cutoff")
                continue

            row = {
                "symbol": symbol,
                "timeframe": timeframe,
                "source": frame_data.get("source"),
                "bars_before_cutoff": len(validated),
                "last_completed_bar": result["last_completed_bar"],
                "patterns_count": len(result["candlestick_patterns"]),
                "patterns": ";".join(x["pattern"] for x in result["candlestick_patterns"]),
                "ema20": result["indicators"]["ema_20"],
                "ema50": result["indicators"]["ema_50"],
                "ema200": result["indicators"]["ema_200"],
                "rsi14": result["indicators"]["rsi_14"],
                "atr14": result["indicators"]["atr_14"],
                "adx14": result["indicators"]["adx_14"],
                "relative_volume20": result["indicators"]["relative_volume_20"],
                "confirmed_pivots": result["levels"]["confirmed_pivot_count"],
                "zones_count": len(result["levels"]["zones"]),
                "channel_type": (result["channel"] or {}).get("channel_type"),
                "channel_window_bars": (result["channel"] or {}).get("window_bars"),
            }
            summary.append(row)
            reports.append({"symbol": symbol, "timeframe": timeframe, "analysis": result})

    expected = len(universe) * len(TIMEFRAMES)
    if len(summary) != expected or errors:
        (OUT / "errors.json").write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError(f"Analysis incomplete: {len(summary)}/{expected} successful; errors={len(errors)}. See errors.json")

    with (OUT / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    (OUT / "features.json").write_text(json.dumps({
        "source_run_id": 44861047844,
        "source_artifact_id": 14690518588,
        "source_artifact_sha256": digest,
        "generated_from_frozen_data_at": payload.get("generated_at_utc"),
        "holdout_cutoff_exclusive": CUTOFF.isoformat(),
        "holdout_bars_excluded": excluded_holdout_bars,
        "universe": universe,
        "timeframes": list(TIMEFRAMES),
        "analysis_count": len(reports),
        "analysis_mode": "DESCRIPTIVE_ONLY_NO_TRADING_SIGNALS",
        "results": reports,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    channels = Counter(row["channel_type"] or "NOT_ENOUGH_HISTORY" for row in summary)
    pattern_rows = sum(row["patterns_count"] > 0 for row in summary)
    print(json.dumps({
        "status": "PASS",
        "symbols": len(universe),
        "timeframes": list(TIMEFRAMES),
        "analyses": len(summary),
        "holdout_cutoff_exclusive": CUTOFF.isoformat(),
        "holdout_bars_excluded": excluded_holdout_bars,
        "latest_analyzed_bar": max(row["last_completed_bar"] for row in summary),
        "pattern_detections_nonzero": pattern_rows,
        "channel_classification_counts": dict(channels),
        "errors": 0,
        "outputs": ["ta-real-data-report/summary.csv", "ta-real-data-report/features.json"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
