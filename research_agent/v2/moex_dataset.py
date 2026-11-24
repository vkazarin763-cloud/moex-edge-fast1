"""Strict loader for frozen MOEX multi-timeframe research artifacts.

Only native TQBR D1 candles strictly before the prospective holdout date are
returned. Post-holdout OHLCV values are never parsed or passed to research.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any


class MOEXDatasetError(ValueError):
    """Invalid or untrusted MOEX research artifact."""


def load_pre_holdout_d1(
    data_path: str | Path,
    validation_path: str | Path,
    *,
    holdout_start: str = "2026-11-20",
) -> dict[str, Any]:
    cutoff = date.fromisoformat(holdout_start)
    try:
        report = json.loads(Path(data_path).read_text(encoding="utf-8"))
        validation = json.loads(Path(validation_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MOEXDatasetError(f"cannot read MOEX dataset/validation JSON: {exc}") from exc
    if not isinstance(report, dict) or not isinstance(validation, dict):
        raise MOEXDatasetError("dataset and validation must be JSON objects")
    if validation.get("status") != "PASS" or validation.get("issue_count") != 0:
        raise MOEXDatasetError("multi-timeframe validation must be PASS with zero issues")
    generated = report.get("generated_at_utc")
    if not isinstance(generated, str) or validation.get("generated_at_utc") != generated:
        raise MOEXDatasetError("dataset and validation provenance timestamps do not match")
    try:
        generated_dt = datetime.fromisoformat(generated.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MOEXDatasetError("invalid generated_at_utc") from exc
    if generated_dt.tzinfo is None or generated_dt.utcoffset() is None:
        raise MOEXDatasetError("generated_at_utc must be timezone-aware")
    if report.get("timezone") != "Europe/Moscow":
        raise MOEXDatasetError("unexpected exchange timezone metadata")

    universe = report.get("universe")
    results = report.get("results")
    if not isinstance(universe, list) or not universe or not isinstance(results, dict):
        raise MOEXDatasetError("dataset must contain a non-empty universe and results mapping")
    if len(universe) != len(set(universe)) or set(universe) != set(results):
        raise MOEXDatasetError("universe and result symbols must match exactly without duplicates")

    symbols: dict[str, list[dict[str, Any]]] = {}
    symbol_metadata: dict[str, dict[str, Any]] = {}
    total_excluded = 0
    for symbol in universe:
        if not isinstance(symbol, str) or not symbol.strip():
            raise MOEXDatasetError("universe contains an invalid symbol")
        frames = results[symbol]
        if not isinstance(frames, dict) or not isinstance(frames.get("D1"), dict):
            raise MOEXDatasetError(f"{symbol}: missing native D1 dataset")
        daily = frames["D1"]
        if daily.get("source") != "MOEX ISS TQBR history" or daily.get("status") != "OK":
            raise MOEXDatasetError(f"{symbol}: D1 source/status is not trusted")
        candles = daily.get("candles")
        if not isinstance(candles, list) or not candles:
            raise MOEXDatasetError(f"{symbol}: D1 candles are missing")

        accepted: list[dict[str, Any]] = []
        previous: date | None = None
        excluded = 0
        for index, row in enumerate(candles):
            if not isinstance(row, dict) or not isinstance(row.get("timestamp"), str):
                raise MOEXDatasetError(f"{symbol}: malformed D1 row {index}")
            try:
                stamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            except ValueError as exc:
                raise MOEXDatasetError(f"{symbol}: invalid D1 timestamp at row {index}") from exc
            if stamp.tzinfo is not None and stamp.utcoffset() is not None:
                raise MOEXDatasetError(f"{symbol}: native MOEX D1 timestamp must remain exchange-local")
            if stamp.date() >= cutoff:
                # Deliberately do not parse any OHLCV field on/after the holdout boundary.
                excluded += 1
                continue
            if previous is not None and stamp.date() <= previous:
                raise MOEXDatasetError(f"{symbol}: duplicate or non-monotonic pre-holdout D1 dates")
            previous = stamp.date()
            values = {}
            for field in ("open", "high", "low", "close", "volume"):
                raw = row.get(field)
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    raise MOEXDatasetError(f"{symbol}: invalid {field} at D1 row {index}")
                number = float(raw)
                if not math.isfinite(number):
                    raise MOEXDatasetError(f"{symbol}: non-finite {field} at D1 row {index}")
                values[field] = number
            o, h, low, close, volume = (values[k] for k in ("open", "high", "low", "close", "volume"))
            if min(o, h, low, close) <= 0 or volume < 0:
                raise MOEXDatasetError(f"{symbol}: non-positive price or negative volume at D1 row {index}")
            if h < max(o, close, low) or low > min(o, close, h):
                raise MOEXDatasetError(f"{symbol}: invalid OHLC relationship at D1 row {index}")
            accepted.append({"timestamp": stamp.isoformat(), **values})

        if len(accepted) < 40:
            raise MOEXDatasetError(f"{symbol}: fewer than 40 pre-holdout D1 bars")
        symbols[symbol] = accepted
        total_excluded += excluded
        symbol_metadata[symbol] = {
            "source": daily["source"],
            "raw_d1_bars": len(candles),
            "pre_holdout_d1_bars": len(accepted),
            "post_holdout_rows_excluded": excluded,
            "first_pre_holdout_date": accepted[0]["timestamp"][:10],
            "last_pre_holdout_date": accepted[-1]["timestamp"][:10],
        }

    return {
        "generated_at_utc": generated,
        "holdout_start": cutoff.isoformat(),
        "universe_size": len(symbols),
        "symbols": symbols,
        "symbol_metadata": symbol_metadata,
        "total_pre_holdout_bars": sum(len(rows) for rows in symbols.values()),
        "post_holdout_rows_excluded": total_excluded,
        "validation": {"status": validation["status"], "issue_count": validation["issue_count"]},
        "safety": {
            "post_holdout_ohlcv_parsed": False,
            "post_holdout_rows_used_for_features": False,
            "post_holdout_rows_used_for_generation_or_selection": False,
            "native_d1_source_only": True,
        },
    }
