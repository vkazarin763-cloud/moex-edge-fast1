"""Reproducible, equities-only MOEX replay of the published Donchian/Turtle 20/10 signal.

This is a research diagnostic, not a portfolio backtest or a live signal generator.
"""
from __future__ import annotations

import argparse
import json
import statistics
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# Historical price factor applied to bars strictly BEFORE the first post-action
# trading date. Volume is adjusted by the inverse factor for a pure split.
CORPORATE_ACTIONS = {
    "TRNFP": [{"effective_date": "2024-02-21", "price_factor": 0.01, "event": "split 1:100", "source": "https://www.moex.com/n67684"}],
    "GMKN": [{"effective_date": "2024-04-08", "price_factor": 0.01, "event": "split 1:100", "source": "https://www.moex.com/n68799"}],
    "VTBR": [{"effective_date": "2024-07-15", "price_factor": 5000.0, "event": "consolidation 5000:1", "source": "https://www.moex.com/n71160"}],
    "PLZL": [{"effective_date": "2025-03-27", "price_factor": 0.1, "event": "split 1:10", "source": "https://www.moex.com/n88888"}],
    "T": [{"effective_date": "2026-04-17", "price_factor": 0.1, "event": "split 1:10", "source": "https://www.moex.com/n99355"}],
}

EXPECTED_UNIVERSE = [
    "AFKS", "AFLT", "ALRS", "BSPB", "CBOM", "CHMF", "CNRU", "DOMRF",
    "ENPG", "FLOT", "GAZP", "GMKN", "HEAD", "IRAO", "LKOH", "MAGN",
    "MDMG", "MOEX", "MTSS", "NLMK", "NVTK", "OZON", "PHOR", "PLZL",
    "POSI", "RAGR", "RENI", "ROSN", "RTKM", "RUAL", "SBER", "SBERP",
    "SNGS", "SNGSP", "SVCB", "T", "TATN", "TATNP", "TRNFP", "UGLD",
    "VKCO", "VTBR", "X5", "YDEX",
]


def adjust_candle(symbol: str, candle: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of one OHLCV candle expressed in post-action price units."""
    result = dict(candle)
    stamp = date.fromisoformat(str(candle["timestamp"])[:10])
    for action in CORPORATE_ACTIONS.get(symbol, []):
        if stamp < date.fromisoformat(action["effective_date"]):
            factor = float(action["price_factor"])
            for field in ("open", "high", "low", "close"):
                result[field] = float(result[field]) * factor
            if result.get("volume") is not None:
                result["volume"] = float(result["volume"]) / factor
    return result


def _validate_rows(symbol: str, rows: list[dict[str, Any]]) -> dict[str, int]:
    stamps = [str(row["timestamp"]) for row in rows]
    duplicates = len(stamps) - len(set(stamps))
    non_monotonic = sum(stamps[i] <= stamps[i - 1] for i in range(1, len(stamps)))
    invalid_ohlc = 0
    invalid_volume = 0
    for row in rows:
        o, h, low, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        if not (0 < low <= o <= h and low <= c <= h):
            invalid_ohlc += 1
        volume = row.get("volume")
        if volume is not None and float(volume) < 0:
            invalid_volume += 1
    return {
        "bars": len(rows),
        "duplicates": duplicates,
        "non_monotonic": non_monotonic,
        "invalid_ohlc": invalid_ohlc,
        "invalid_volume": invalid_volume,
    }


def _simulate_symbol(symbol: str, rows: list[dict[str, Any]], entry_period: int = 20, exit_period: int = 10):
    """Signal on close; market order fills at next available bar open."""
    trades: list[dict[str, Any]] = []
    pending: str | None = None
    in_position = False
    entry_price = None
    entry_date = None
    entry_index = None

    for index, row in enumerate(rows):
        # Execute only orders generated at the previous completed close.
        if pending == "entry" and not in_position:
            in_position = True
            entry_price = float(row["open"])
            entry_date = str(row["timestamp"])[:10]
            entry_index = index
            pending = None
        elif pending == "exit" and in_position:
            exit_price = float(row["open"])
            trades.append({
                "ticker": symbol,
                "entry_date": entry_date,
                "exit_date": str(row["timestamp"])[:10],
                "entry": entry_price,
                "exit": exit_price,
                "gross_return": exit_price / entry_price - 1.0,
                "holding_bars": index - entry_index,
            })
            in_position = False
            entry_price = entry_date = entry_index = None
            pending = None

        if index < entry_period:
            continue
        prior = rows[:index]
        prior_high = max(float(item["high"]) for item in prior[-entry_period:])
        prior_low = min(float(item["low"]) for item in prior[-exit_period:])
        close = float(row["close"])

        if in_position:
            if close < prior_low:
                pending = "exit"
        elif close > prior_high:
            pending = "entry"

    open_position = None
    if in_position:
        last = rows[-1]
        open_position = {
            "ticker": symbol,
            "entry_date": entry_date,
            "entry": entry_price,
            "last_date": str(last["timestamp"])[:10],
            "last_close": float(last["close"]),
            "unrealized_gross_return": float(last["close"]) / entry_price - 1.0,
        }
    return trades, open_position


def _trade_metrics(trades: list[dict[str, Any]], cost_bps_per_side: float) -> dict[str, Any]:
    if not trades:
        return {"closed_trades": 0, "cost_bps_per_side": cost_bps_per_side}
    cost = cost_bps_per_side / 10_000.0
    returns = [
        (float(t["exit"]) * (1.0 - cost)) / (float(t["entry"]) * (1.0 + cost)) - 1.0
        for t in trades
    ]
    winners = [value for value in returns if value > 0]
    losers = [value for value in returns if value < 0]
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    return {
        "closed_trades": len(returns),
        "cost_bps_per_side": cost_bps_per_side,
        "average_net_trade_return": statistics.mean(returns),
        "median_net_trade_return": statistics.median(returns),
        "win_rate": len(winners) / len(returns),
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "average_holding_bars": statistics.mean(float(t["holding_bars"]) for t in trades),
    }


def _load_dataset(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            matches = [name for name in archive.namelist() if name.endswith("moex_edge_multi_timeframe_candles.json")]
            if len(matches) != 1:
                raise ValueError("ZIP must contain exactly one moex_edge_multi_timeframe_candles.json")
            return json.loads(archive.read(matches[0]))
    return json.loads(path.read_text(encoding="utf-8"))


def run_replay(
    dataset: dict[str, Any],
    *,
    holdout_start: str = "2026-11-20",
    cost_scenarios_bps: tuple[float, ...] = (0.0, 8.0, 16.0, 32.0),
) -> dict[str, Any]:
    universe = dataset.get("universe")
    if universe != EXPECTED_UNIVERSE:
        raise ValueError("Dataset universe does not match the frozen MOEX 44")
    cutoff = date.fromisoformat(holdout_start)
    all_trades: list[dict[str, Any]] = []
    open_positions: list[dict[str, Any]] = []
    validation: dict[str, Any] = {}
    excluded_holdout_bars = 0

    for symbol in universe:
        block = dataset.get("results", {}).get(symbol, {}).get("D1", {})
        raw_rows = block.get("candles") or []
        rows = []
        for raw in raw_rows:
            stamp = date.fromisoformat(str(raw["timestamp"])[:10])
            if stamp >= cutoff:
                excluded_holdout_bars += 1
                continue
            rows.append(adjust_candle(symbol, raw))
        rows.sort(key=lambda row: str(row["timestamp"]))
        check = _validate_rows(symbol, rows)
        validation[symbol] = check
        if check["duplicates"] or check["non_monotonic"] or check["invalid_ohlc"] or check["invalid_volume"]:
            raise ValueError(f"{symbol}: invalid D1 data after corporate-action adjustment: {check}")
        trades, open_position = _simulate_symbol(symbol, rows)
        all_trades.extend(trades)
        if open_position:
            open_positions.append(open_position)

    yearly: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in all_trades:
        yearly[trade["exit_date"][:4]].append(trade)

    total_bars = sum(item["bars"] for item in validation.values())
    return {
        "report_version": "moex-donchian-20-10-replay-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_as_of_utc": dataset.get("generated_at_utc"),
        "holdout_start_exclusive": holdout_start,
        "holdout_bars_excluded": excluded_holdout_bars,
        "universe": universe,
        "strategy": {
            "source": "https://github.com/bmonagan/backtester",
            "source_commit": "ba5156ec58f8d240af7b09b476fa8493171228d3",
            "entry": "Long when completed daily close > highest high of prior 20 completed bars",
            "exit": "Exit when completed daily close < lowest low of prior 10 completed bars",
            "execution": "Signal at close; order fills at next available daily open",
            "shorts": False,
            "stops": False,
            "pyramiding": False,
        },
        "corporate_actions_applied": CORPORATE_ACTIONS,
        "data_validation": {
            "symbols": len(validation),
            "total_d1_bars_before_holdout": total_bars,
            "duplicates": sum(x["duplicates"] for x in validation.values()),
            "non_monotonic": sum(x["non_monotonic"] for x in validation.values()),
            "invalid_ohlc": sum(x["invalid_ohlc"] for x in validation.values()),
            "invalid_volume": sum(x["invalid_volume"] for x in validation.values()),
            "per_symbol": validation,
        },
        "summary": {
            "closed_trades": len(all_trades),
            "symbols_with_closed_trades": len({t["ticker"] for t in all_trades}),
            "open_positions_at_cutoff": len(open_positions),
            "trade_metrics_by_cost_scenario": [
                _trade_metrics(all_trades, scenario) for scenario in cost_scenarios_bps
            ],
            "by_exit_year_at_8bps_per_side": {
                year: _trade_metrics(trades, 8.0) for year, trades in sorted(yearly.items())
            },
        },
        "open_positions": open_positions,
        "trades": all_trades,
        "limitations": [
            "Trade-level diagnostic only; no portfolio return, CAGR or capital-allocation result is calculated.",
            "The current 44-stock universe applied retrospectively has survivorship/universe-selection bias.",
            "Corporate-action adjustments cover only the explicitly documented events listed in this report; a full issuer corporate-action ledger is still required.",
            "Cash dividends are not included in price returns.",
            "Cost scenarios are assumptions, not verified broker tariffs or measured bid/ask execution costs.",
            "No intraday liquidity, partial fills, market impact or limit-up/limit-down execution is modeled.",
            "The 2026-11-20-and-later holdout bars are excluded and must remain sealed.",
            "A positive pooled trade statistic is not evidence of a deployable or profitable MOEX strategy.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="MOEX multi-timeframe JSON or ZIP artifact")
    parser.add_argument("--output", default="moex_donchian_20_10_replay.json")
    parser.add_argument("--holdout-start", default="2026-11-20")
    args = parser.parse_args(argv)
    report = run_replay(_load_dataset(Path(args.input)), holdout_start=args.holdout_start)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "REPLAY_COMPLETED",
        "closed_trades": report["summary"]["closed_trades"],
        "open_positions": report["summary"]["open_positions_at_cutoff"],
        "data_validation": report["data_validation"],
        "cost_scenarios": report["summary"]["trade_metrics_by_cost_scenario"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
