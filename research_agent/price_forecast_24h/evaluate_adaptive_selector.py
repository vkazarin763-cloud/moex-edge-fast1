"""Causal walk-forward adaptive selector for H1 strategy candidates.

Research-only. At each signal close, the selector uses only candidate trades
whose exits occurred strictly before the current signal. It estimates each
rule's recent performance in the same ticker-specific joint trend/volatility
regime, requires a minimum sample, and chooses at most one rule/position.
"""
from __future__ import annotations
import gzip, json, math, statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from research_agent.price_forecast_24h.evaluate_direction_mechanics import (
    ROOT, MIN_BARS, HOLDOUT_FRAC, indicators, make_signals, VARIANTS
)
from research_agent.price_forecast_24h.evaluate_market_regime_attribution import build_regimes
from research_agent.price_forecast_24h.evaluate_ohlc_strategies import clean_bars, stats

MAX_HOLD = 12
WARMUP_FRAC_OF_DEVELOPMENT = 0.50
ROLLING_CANDIDATES = 100
MIN_TRAIN_TRADES = 30
TRAIN_COST_BPS = 10
EVAL_COSTS = (5, 10)
PERIODS = ("development_fold_1", "development_fold_2", "development_fold_3", "holdout")

def joint_regime(regime):
    return regime["trend_strength"] + "|" + regime["volatility"]

def make_candidate_trades(bars, signals, regimes, ticker):
    """One non-overlapping hypothetical candidate stream per rule."""
    by_rule = {}
    for rule in VARIANTS:
        trades = []
        i = 0
        while i < len(bars) - 1:
            direction = signals[rule][i]
            if not direction:
                i += 1
                continue
            entry_i = i + 1
            exit_i = min(len(bars) - 1, entry_i + MAX_HOLD - 1)
            entry, exitp = bars[entry_i]["open"], bars[exit_i]["close"]
            if entry > 0 and exitp > 0:
                trades.append({
                    "ticker": ticker, "rule": rule, "signal_i": i, "exit_i": exit_i,
                    "regime": joint_regime(regimes[i]),
                    "gross_return": direction * math.log(exitp / entry),
                    "holding_bars": exit_i - entry_i + 1,
                    "signal_time": bars[i]["timestamp"],
                    "exit_time": bars[exit_i]["timestamp"],
                    "direction": "LONG" if direction == 1 else "SHORT",
                })
            i = exit_i + 1
        by_rule[rule] = trades
    return by_rule

def training_score(history):
    """Conservative fixed score: rolling mean and PF after 20bp round-trip cost."""
    sample = history[-ROLLING_CANDIDATES:]
    if len(sample) < MIN_TRAIN_TRADES:
        return None
    net = [t["gross_return"] - 2 * TRAIN_COST_BPS / 10000 for t in sample]
    wins = [x for x in net if x > 0]
    losses = [x for x in net if x < 0]
    mean = statistics.fmean(net)
    pf = sum(wins) / abs(sum(losses)) if losses else (float("inf") if wins else 0.0)
    if mean <= 0 or pf <= 1.0:
        return None
    return {"score": mean, "profit_factor": pf, "sample": len(sample)}

def summarize(trades):
    return {
        "trades": len(trades),
        "5bps": stats(trades, 5),
        "10bps": stats(trades, 10),
        "long_trades": sum(t["direction"] == "LONG" for t in trades),
        "short_trades": sum(t["direction"] == "SHORT" for t in trades),
        "selected_rules": {
            rule: sum(t["rule"] == rule for t in trades) for rule in VARIANTS
        },
    }

def evaluate_ticker(ticker, bars):
    ema, sma, atr = indicators(bars)
    regimes = build_regimes(bars, sma, atr)
    signals = make_signals(bars, ema, sma)
    candidates = make_candidate_trades(bars, signals, regimes, ticker)

    # Candidate opportunities are precomputed, but become trainable only after
    # their actual exit index is strictly earlier than the current signal index.
    completion_queue = sorted(
        (t for stream in candidates.values() for t in stream),
        key=lambda t: (t["exit_i"], t["signal_i"], t["rule"])
    )
    candidate_at_signal = defaultdict(list)
    for rule, stream in candidates.items():
        for t in stream:
            candidate_at_signal[t["signal_i"]].append(t)

    history = defaultdict(list)
    queue_pos = 0
    cutoff = int(len(bars) * (1 - HOLDOUT_FRAC))
    eval_start = int(cutoff * (1 - WARMUP_FRAC_OF_DEVELOPMENT))
    fold_start = eval_start
    fold_width = (cutoff - eval_start) // 3
    folds = [
        (fold_start + k * fold_width, cutoff if k == 2 else fold_start + (k + 1) * fold_width)
        for k in range(3)
    ]
    boundaries = [a for a, _ in folds[1:]] + [cutoff]
    selected = []
    no_trade_signals = 0
    eligible_signals = 0
    selected_exit_i = -1
    period_counts = defaultdict(lambda: {"eligible_signals": 0, "selected": 0, "no_trade": 0})

    def period_for(i):
        if i >= cutoff:
            return "holdout"
        for n, (a, b) in enumerate(folds, 1):
            if a <= i < b:
                return f"development_fold_{n}"
        return "warmup"

    for i in range(eval_start, len(bars) - 1):
        # Strict causality: a candidate's exit must precede this signal bar.
        while queue_pos < len(completion_queue) and completion_queue[queue_pos]["exit_i"] < i:
            t = completion_queue[queue_pos]
            history[(t["rule"], t["regime"])].append(t)
            queue_pos += 1

        current_period = period_for(i)
        if current_period == "warmup":
            continue
        current = candidate_at_signal.get(i, [])
        if not current:
            continue
        eligible_signals += len(current)
        period_counts[current_period]["eligible_signals"] += len(current)

        if i <= selected_exit_i:
            no_trade_signals += len(current)
            period_counts[current_period]["no_trade"] += len(current)
            continue

        scored = []
        for candidate in current:
            key = (candidate["rule"], candidate["regime"])
            score = training_score(history[key])
            if score is not None:
                scored.append((score["score"], score["profit_factor"], candidate["rule"], candidate, score))
        if not scored:
            no_trade_signals += len(current)
            period_counts[current_period]["no_trade"] += len(current)
            continue

        # Deterministic tie-break: higher mean, then PF, then alphabetical rule.
        scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
        _, _, _, candidate, train = scored[0]
        # Execute the chosen candidate's same next-bar-open / fixed-time-exit trade.
        entry_i = i + 1
        exit_i = candidate["exit_i"]
        direction = candidate["direction"]
        entry = bars[entry_i]["open"]
        exitp = bars[exit_i]["close"]
        gross = (1 if direction == "LONG" else -1) * math.log(exitp / entry)
        selected.append({
            "ticker": ticker, "rule": candidate["rule"], "direction": direction,
            "signal_time": candidate["signal_time"], "entry_time": bars[entry_i]["timestamp"],
            "exit_time": candidate["exit_time"], "signal_i": i, "exit_i": exit_i,
            "regime": candidate["regime"], "gross_return": gross,
            "holding_bars": candidate["holding_bars"],
            "training_sample": train["sample"],
            "training_mean_net_10bps_pct": train["score"] * 100,
            "training_profit_factor_10bps": train["profit_factor"],
            "period": current_period,
        })
        period_counts[current_period]["selected"] += 1
        selected_exit_i = exit_i

    by_period = {}
    for period in PERIODS:
        subset = [t for t in selected if t["period"] == period]
        by_period[period] = {
            "performance": summarize(subset),
            **period_counts[period],
        }
    return {
        "selected": selected,
        "periods": by_period,
        "eligible_signals": eligible_signals,
        "no_trade_signals": no_trade_signals,
        "candidate_trade_counts": {r: len(candidates[r]) for r in VARIANTS},
        "warmup_start": bars[0]["timestamp"],
        "evaluation_start": bars[eval_start]["timestamp"],
        "holdout_start": bars[cutoff]["timestamp"],
        "data_end": bars[-1]["timestamp"],
    }

def main():
    data_path = ROOT / "data" / "H1_HISTORY.json.gz"
    if not data_path.exists():
        raise SystemExit("H1_HISTORY.json.gz missing")
    with gzip.open(data_path, "rt", encoding="utf-8") as f:
        payload = json.load(f)

    symbols = {}
    all_selected = []
    excluded = {}
    candidate_totals = defaultdict(int)
    for ticker, obj in payload.get("symbols", {}).items():
        bars, quality = clean_bars(obj["candles"])
        if len(bars) < MIN_BARS:
            excluded[ticker] = {"bars": len(bars), "reason": "MIN_BARS", **quality}
            continue
        result = evaluate_ticker(ticker, bars)
        all_selected.extend(result.pop("selected"))
        for rule, count in result["candidate_trade_counts"].items():
            candidate_totals[rule] += count
        symbols[ticker] = {"status": "OK", **result, "data_quality": quality}

    aggregate = {}
    for period in PERIODS:
        subset = [t for t in all_selected if t["period"] == period]
        aggregate[period] = summarize(subset)

    period_activity = {}
    for period in PERIODS:
        eligible = sum(v["periods"][period]["eligible_signals"] for v in symbols.values())
        selected = sum(v["periods"][period]["selected"] for v in symbols.values())
        no_trade = sum(v["periods"][period]["no_trade"] for v in symbols.values())
        period_activity[period] = {
            "eligible_signals": eligible, "selected_trades": selected,
            "no_trade_signals": no_trade,
            "no_trade_pct": (no_trade / eligible * 100) if eligible else None,
        }

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "data_source": "Finam technical H1 archive",
        "symbols_evaluated": len(symbols),
        "symbols_excluded": excluded,
        "protocol": {
            "selector": "At each candidate signal, use only hypothetical candidate trades whose exits are strictly before the current signal bar. Maintain a rolling history of up to 100 completed candidate trades per ticker/rule/joint regime. Require at least 30 observations. Score each rule by mean net return after 10 bps per side; require mean > 0 and profit factor > 1.0. Select highest score; deterministic tie-break by PF then rule name. If no rule qualifies, no trade.",
            "regime": "Ticker-specific causal trend-strength and ATR/close volatility ranks; low/mid/high terciles from up to 120 prior observations, at least 60 prior observations, current bar excluded.",
            "candidate_streams": "Six predeclared rules; one non-overlapping hypothetical trade per ticker/rule at a time; next H1 open entry, close after at most 12 H1 bars.",
            "execution": "At most one selected trade per ticker at a time across all rules; no overlapping selected trades. Signal on completed H1 close, entry next H1 open.",
            "walk_forward": "First half of first 80% is warm-up/training only. Remaining first 80% is three chronological evaluation folds. Final 20% is later holdout. Selector state carries forward causally; at each decision only completed prior outcomes are available.",
            "costs": "Selector training threshold uses 10 bps per side (20 bps round-trip). Reported performance uses 5 and 10 bps per side; illustrative only.",
            "tie_break": "Higher rolling mean net return, then higher PF, then alphabetical rule name."
        },
        "aggregate": aggregate,
        "activity_by_period": period_activity,
        "candidate_trade_counts": dict(candidate_totals),
        "limitations": [
            "Diagnostic only: the same historical archive and final 20% have been examined in earlier experiments; this is not an independent confirmatory sample.",
            "Candidate training outcomes are hypothetical per-rule streams and may overlap across rules; selected evaluation trades themselves do not overlap per ticker.",
            "Ticker-specific regimes are not a common MOEX-wide market regime.",
            "Actual spreads, commissions, slippage, short borrow availability/cost, taxes and market impact are not modeled; cost assumptions are illustrative.",
            "Finam H1 bars are technical data; 12 bars do not necessarily equal 12 clock hours.",
            "Pooled trade-chain metrics are diagnostics, not portfolio returns.",
            "Research only: no production, real signals, Telegram notifications, cron changes, secrets or broker orders."
        ]
    }
    out = ROOT / "reports"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = out / f"adaptive-selector-{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "OK", "symbols_evaluated": len(symbols),
        "aggregate": aggregate, "activity_by_period": period_activity,
        "candidate_trade_counts": dict(candidate_totals),
        "report": str(report_path)
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
