#!/usr/bin/env python3
"""Run the pinned model backtest and emit direction-separated, amount-free metrics."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from moex_agent.backtest import Backtester


def metrics(trades):
    returns = [float(t.pnl_pct) for t in trades]
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_win / gross_loss if gross_loss else (math.inf if gross_win else 0.0)
    ordered = sorted(trades, key=lambda t: t.exit_time)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else 0.0,
        "avg_trade_return_pct": round(sum(returns) / len(returns), 4) if returns else 0.0,
        "median_trade_return_pct": round(sorted(returns)[len(returns)//2], 4) if returns else 0.0,
        "profit_factor": round(pf, 4) if math.isfinite(pf) else "infinity",
        "exit_reasons": dict(Counter(t.exit_reason for t in ordered)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    start = (today - timedelta(days=args.days)).isoformat()
    end = today.isoformat()

    tester = Backtester(config_path=args.config, initial_capital=1_000_000, position_size_pct=0.05)
    result = tester.run(start_date=start, end_date=end, verbose=True)
    trades = result.trades
    by_direction = {
        direction: metrics([t for t in trades if t.direction == direction])
        for direction in ("LONG", "SHORT")
    }
    by_horizon = {
        horizon: metrics([t for t in trades if t.horizon == horizon])
        for horizon in sorted({t.horizon for t in trades})
    }
    summary = {
        "period": {"from": start, "to": end},
        "model_horizons": ["5m", "10m", "30m", "1h"],
        "total": metrics(trades),
        "by_direction": by_direction,
        "by_horizon": by_horizon,
        "caveats": [
            "Paper simulation only; no broker orders.",
            "Returns are per-trade percentages after the backtest's configured spread and commission assumptions.",
            "Overlapping positions and portfolio-level capital constraints are not independently modeled.",
            "The backtest uses the upstream anomaly and exit logic with direction correction and conservative same-candle stop handling.",
        ],
    }
    Path("data").mkdir(exist_ok=True)
    Path("data/backtest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with Path("data/backtest_trades.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "ticker", "direction", "entry_time", "exit_time", "entry_price",
            "exit_price", "return_pct", "horizon", "probability", "exit_reason",
        ])
        writer.writeheader()
        for t in trades:
            writer.writerow({
                "ticker": t.ticker,
                "direction": t.direction,
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat(),
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "return_pct": t.pnl_pct,
                "horizon": t.horizon,
                "probability": t.probability,
                "exit_reason": t.exit_reason,
            })
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not trades:
        print("BACKTEST_WARNING: zero completed trades; no profitability conclusion possible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
