"""Load historical formation data and genuinely fresh forward candles.

The sealed 2026-11-20 date is excluded without parsing its OHLCV values.
Rows strictly after that date form a separate forward-evaluation partition.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any


class MOEXForwardDatasetError(ValueError):
    """Invalid or insufficient forward-validation artifact."""


def load_formation_and_forward_d1(
    data_path: str | Path,
    validation_path: str | Path,
    *,
    sealed_through: str = "2026-11-20",
    minimum_forward_bars: int = 20,
) -> dict[str, Any]:
    sealed_date = date.fromisoformat(sealed_through)
    if isinstance(minimum_forward_bars, bool) or not isinstance(minimum_forward_bars, int) or minimum_forward_bars < 1:
        raise MOEXForwardDatasetError("minimum_forward_bars must be a positive integer")
    try:
        report = json.loads(Path(data_path).read_text(encoding="utf-8"))
        validation = json.loads(Path(validation_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MOEXForwardDatasetError(f"cannot read dataset/validation JSON: {exc}") from exc
    if not isinstance(report, dict) or not isinstance(validation, dict):
        raise MOEXForwardDatasetError("dataset and validation must be JSON objects")
    if validation.get("status") != "PASS" or validation.get("issue_count") != 0:
        raise MOEXForwardDatasetError("collector validation must be PASS with zero issues")
    generated = report.get("generated_at_utc")
    if not isinstance(generated, str) or validation.get("generated_at_utc") != generated:
        raise MOEXForwardDatasetError("dataset and validation provenance timestamps do not match")
    try:
        generated_dt = datetime.fromisoformat(generated.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MOEXForwardDatasetError("invalid generated_at_utc") from exc
    if generated_dt.tzinfo is None or generated_dt.utcoffset() is None:
        raise MOEXForwardDatasetError("generated_at_utc must be timezone-aware")
    if report.get("timezone") != "Europe/Moscow":
        raise MOEXForwardDatasetError("unexpected exchange timezone metadata")

    universe, results = report.get("universe"), report.get("results")
    if not isinstance(universe, list) or not universe or not isinstance(results, dict):
        raise MOEXForwardDatasetError("dataset must contain a non-empty universe and results mapping")
    if len(universe) != len(set(universe)) or set(universe) != set(results):
        raise MOEXForwardDatasetError("universe/results mismatch or duplicate symbols")

    formation_symbols: dict[str, list[dict[str, Any]]] = {}
    forward_symbols: dict[str, list[dict[str, Any]]] = {}
    sealed_rows_skipped = 0
    all_forward_dates: set[str] = set()
    metadata: dict[str, dict[str, Any]] = {}

    for symbol in universe:
        if not isinstance(symbol, str) or not symbol.strip():
            raise MOEXForwardDatasetError("universe contains an invalid symbol")
        frames = results[symbol]
        if not isinstance(frames, dict) or not isinstance(frames.get("D1"), dict):
            raise MOEXForwardDatasetError(f"{symbol}: missing native D1 dataset")
        daily = frames["D1"]
        if daily.get("source") != "MOEX ISS TQBR history" or daily.get("status") != "OK":
            raise MOEXForwardDatasetError(f"{symbol}: D1 source/status is not trusted")
        candles = daily.get("candles")
        if not isinstance(candles, list) or not candles:
            raise MOEXForwardDatasetError(f"{symbol}: D1 candles are missing")

        formation: list[dict[str, Any]] = []
        forward: list[dict[str, Any]] = []
        previous_date: date | None = None
        for index, row in enumerate(candles):
            if not isinstance(row, dict) or not isinstance(row.get("timestamp"), str):
                raise MOEXForwardDatasetError(f"{symbol}: malformed D1 row {index}")
            try:
                stamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            except ValueError as exc:
                raise MOEXForwardDatasetError(f"{symbol}: invalid timestamp at row {index}") from exc
            if stamp.tzinfo is not None and stamp.utcoffset() is not None:
                raise MOEXForwardDatasetError(f"{symbol}: D1 timestamp must be exchange-local")
            day = stamp.date()
            if previous_date is not None and day <= previous_date:
                raise MOEXForwardDatasetError(f"{symbol}: duplicate or non-monotonic D1 dates")
            previous_date = day

            if day == sealed_date:
                # The old pilot holdout remains sealed: do not parse its OHLCV.
                sealed_rows_skipped += 1
                continue
            target = formation if day < sealed_date else forward
            values: dict[str, float] = {}
            for field in ("open", "high", "low", "close", "volume"):
                raw = row.get(field)
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    raise MOEXForwardDatasetError(f"{symbol}: invalid {field} at row {index}")
                number = float(raw)
                if not math.isfinite(number):
                    raise MOEXForwardDatasetError(f"{symbol}: non-finite {field} at row {index}")
                values[field] = number
            o, h, low, close, volume = (values[k] for k in ("open", "high", "low", "close", "volume"))
            if min(o, h, low, close) <= 0 or volume < 0:
                raise MOEXForwardDatasetError(f"{symbol}: non-positive price or negative volume at row {index}")
            if h < max(o, close, low) or low > min(o, close, h):
                raise MOEXForwardDatasetError(f"{symbol}: invalid OHLC relationship at row {index}")
            accepted = {"timestamp": stamp.isoformat(), **values}
            target.append(accepted)
            if day > sealed_date:
                all_forward_dates.add(day.isoformat())

        if len(formation) < 40:
            raise MOEXForwardDatasetError(f"{symbol}: fewer than 40 historical formation bars")
        formation_symbols[symbol] = formation
        forward_symbols[symbol] = forward
        metadata[symbol] = {
            "formation_bars": len(formation),
            "forward_bars": len(forward),
            "last_formation_date": formation[-1]["timestamp"][:10],
            "first_forward_date": forward[0]["timestamp"][:10] if forward else None,
            "last_forward_date": forward[-1]["timestamp"][:10] if forward else None,
        }

    minimum_observed = min((len(rows) for rows in forward_symbols.values()), default=0)
    ready = minimum_observed >= minimum_forward_bars
    return {
        "generated_at_utc": generated,
        "sealed_through": sealed_date.isoformat(),
        "universe_size": len(formation_symbols),
        "formation_symbols": formation_symbols,
        "forward_symbols": forward_symbols,
        "symbol_metadata": metadata,
        "forward_date_count": len(all_forward_dates),
        "minimum_forward_bars_per_symbol": minimum_observed,
        "minimum_forward_bars_required": minimum_forward_bars,
        "ready_for_forward_evaluation": ready,
        "sealed_date_rows_skipped_without_ohlcv_parsing": sealed_rows_skipped,
        "safety": {
            "sealed_date_ohlcv_parsed": False,
            "sealed_date_used_for_features_or_evaluation": False,
            "historical_validation_tail_used": False,
            "forward_rows_used_for_hypothesis_generation": False,
            "forward_rows_reserved_for_independent_evaluation": True,
        },
    }
