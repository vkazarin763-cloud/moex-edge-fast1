"""Causal market suitability gate: trade or stand aside.

Research-only. A market episode is one ticker/H1 signal bar with one or more
predeclared candidate strategy signals. The gate learns from the average
outcome of those candidate signals only after every trade in that episode
has closed. It then either permits all current candidate signals or blocks
the entire episode. This tests market suitability, not strategy selection.
"""
from __future__ import annotations
import gzip, json, math, statistics
from collections import defaultdict
from datetime import datetime, timezone

from research_agent.price_forecast_24h.evaluate_direction_mechanics import (
    ROOT, MIN_BARS, HOLDOUT_FRAC, indicators, make_signals, VARIANTS
)
from research_agent.price_forecast_24h.evaluate_market_regime_attribution import build_regimes
from research_agent.price_forecast_24h.evaluate_ohlc_strategies import clean_bars, stats

MAX_HOLD = 12
ROLLING_EPISODES = 100
MIN_TRAIN_EPISODES = 30
TRAIN_COST_BPS_PER_SIDE = 10
EVAL_COSTS = (5, 10)
DEVELOPMENT_WARMUP_FRACTION = 0.50
PERIODS = ("development_fold_1", "development_fold_2", "development_fold_3", "holdout")

def regime_keys(regime):
    return (
        ("joint", regime["trend_strength"] + "|" + regime["volatility"]),
        ("trend", regime["trend_strength"]),
        ("volatility", regime["volatility"]),
        ("all", "all"),
    )

def build_candidate_trades(bars, signals, regimes, ticker):
    """One non-overlapping hypothetical trade stream per predeclared rule."""
    streams = {}
    by_signal = defaultdict(list)
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
            entry, exit_price = bars[entry_i]["open"], bars[exit_i]["close"]
            if entry > 0 and exit_price > 0:
                trade = {
                    "ticker": ticker, "rule": rule, "signal_i": i, "exit_i": exit_i,
                    "signal_time": bars[i]["timestamp"],
                    "entry_time": bars[entry_i]["timestamp"],
                    "exit_time": bars[exit_i]["timestamp"],
                    "direction": "LONG" if direction == 1 else "SHORT",
                    "gross_return": direction * math.log(exit_price / entry),
                    "holding_bars": exit_i - entry_i + 1,
                    "regime": regimes[i],
                }
                trades.append(trade)
                by_signal[i].append(trade)
            i = exit_i + 1
        streams[rule] = trades
    return streams, by_signal

def episode_observation(candidates):
    # Equal weight per active predeclared rule; not a portfolio return.
    gross = statistics.fmean(t["gross_return"] for t in candidates)
    return {
        "gross_return": gross,
        "exit_i": max(t["exit_i"] for t in candidates),
        "candidate_count": len(candidates),
    }

def gate_score(history):
    sample = history[-ROLLING_EPISODES:]
    if len(sample) < MIN_TRAIN_EPISODES:
        return None
    cost = 2 * TRAIN_COST_BPS_PER_SIDE / 10000
    net = [x["gross_return"] - cost for x in sample]
    gains = sum(x for x in net if x > 0)
    losses = abs(sum(x for x in net if x < 0))
    pf = gains / losses if losses > 0 else (float("inf") if gains > 0 else 0.0)
    mean = statistics.fmean(net)
    if mean <= 0 or pf <= 1.0:
        return None
    return {"mean_net": mean, "profit_factor": pf, "sample": len(sample)}

def summarize(trades):
    return {
        "trades": len(trades),
        "5bps": stats(trades, 5),
        "10bps": stats(trades, 10),
        "long_trades": sum(t["direction"] == "LONG" for t in trades),
        "short_trades": sum(t["direction"] == "SHORT" for t in trades),
    }

def period_bounds(n):
    cutoff = int(n * (1 - HOLDOUT_FRAC))
    eval_start = int(cutoff * DEVELOPMENT_WARMUP_FRACTION)
    width = (cutoff - eval_start) // 3
    folds = [
        (eval_start + k * width, cutoff if k == 2 else eval_start + (k + 1) * width)
        for k in range(3)
    ]
    return cutoff, eval_start, folds

def period_for(i, cutoff, folds):
    if i >= cutoff:
        return "holdout"
    for n, (start, end) in enumerate(folds, 1):
        if start <= i < end:
            return f"development_fold_{n}"
    return "warmup"

def evaluate_ticker(ticker, bars):
    ema, sma, atr = indicators(bars)
    regimes = build_regimes(bars, sma, atr)
    signals = make_signals(bars, ema, sma)
    streams, by_signal = build_candidate_trades(bars, signals, regimes, ticker)
    episodes = []
    for signal_i, candidates in by_signal.items():
        regime = candidates[0]["regime"]
        # Unclassified regimes cannot be used to train or pass the gate.
        if regime["trend_strength"] == "unclassified" or regime["volatility"] == "unclassified":
            continue
        obs = episode_observation(candidates)
        episodes.append({
            "signal_i": signal_i, "exit_i": obs["exit_i"],
            "gross_return": obs["gross_return"], "candidate_count": obs["candidate_count"],
            "keys": regime_keys(regime),
        })
    episodes.sort(key=lambda x: (x["signal_i"], x["exit_i"]))

    cutoff, eval_start, folds = period_bounds(len(bars))
    completion_queue = sorted(episodes, key=lambda x: (x["exit_i"], x["signal_i"]))
    queue_pos = 0
    history = defaultdict(list)
    episode_by_signal = {x["signal_i"]: x for x in episodes}
    all_trades = [t for stream in streams.values() for t in stream]
    trade_by_signal = defaultdict(list)
    for t in all_trades:
        trade_by_signal[t["signal_i"]].append(t)

    baseline_by_period = defaultdict(list)
    filtered_by_period = defaultdict(list)
    event_counts = defaultdict(lambda: {"eligible_episodes": 0, "allowed_episodes": 0, "blocked_episodes": 0})
    gate_scopes = defaultdict(int)
    evaluation_start_time = bars[eval_start]["timestamp"]
    holdout_start_time = bars[cutoff]["timestamp"]

    for i in range(eval_start, len(bars) - 1):
        # Only episodes whose full candidate outcomes closed before this signal
        # may enter the training history.
        while queue_pos < len(completion_queue) and completion_queue[queue_pos]["exit_i"] < i:
            completed = completion_queue[queue_pos]
            for key in completed["keys"]:
                history[key].append(completed)
            queue_pos += 1

        period = period_for(i, cutoff, folds)
        if period == "warmup":
            continue
        current_trades = trade_by_signal.get(i, [])
        if not current_trades:
            continue
        regime = current_trades[0]["regime"]
        if regime["trend_strength"] == "unclassified" or regime["volatility"] == "unclassified":
            continue
        event_counts[period]["eligible_episodes"] += 1
        baseline_by_period[period].extend(current_trades)

        score = None
        chosen_scope = None
        for scope_key in regime_keys(regime):
            score = gate_score(history[scope_key])
            if score is not None:
                chosen_scope = scope_key[0]
                break

        if score is None:
            event_counts[period]["blocked_episodes"] += 1
            continue

        event_counts[period]["allowed_episodes"] += 1
        gate_scopes[chosen_scope] += 1
        for trade in current_trades:
            kept = dict(trade)
            kept["gate_training_sample"] = score["sample"]
            kept["gate_training_scope"] = chosen_scope
            kept["gate_training_mean_net_10bps_pct"] = score["mean_net"] * 100
            filtered_by_period[period].append(kept)

    per_period = {}
    per_rule = {}
    for period in PERIODS:
        base = baseline_by_period[period]
        kept = filtered_by_period[period]
        per_period[period] = {
            "baseline": summarize(base),
            "filtered": summarize(kept),
            "eligible_episodes": event_counts[period]["eligible_episodes"],
            "allowed_episodes": event_counts[period]["allowed_episodes"],
            "blocked_episodes": event_counts[period]["blocked_episodes"],
            "blocked_episode_pct": (
                event_counts[period]["blocked_episodes"] /
                event_counts[period]["eligible_episodes"] * 100
                if event_counts[period]["eligible_episodes"] else None
            ),
            "candidate_signal_rows_removed_pct": (
                (len(base) - len(kept)) / len(base) * 100 if base else None
            ),
        }
        per_rule[period] = {}
        for rule in VARIANTS:
            b = [t for t in base if t["rule"] == rule]
            f = [t for t in kept if t["rule"] == rule]
            per_rule[period][rule] = {"baseline": summarize(b), "filtered": summarize(f)}

    return {
        "periods": per_period,
        "per_rule": per_rule,
        "gate_scope_counts": dict(gate_scopes),
        "candidate_trade_counts": {r: len(streams[r]) for r in VARIANTS},
        "evaluation_start": evaluation_start_time,
        "holdout_start": holdout_start_time,
        "data_end": bars[-1]["timestamp"],
    }

def main():
    data_path = ROOT / "data" / "H1_HISTORY.json.gz"
    if not data_path.exists():
        raise SystemExit("H1_HISTORY.json.gz missing")
    with gzip.open(data_path, "rt", encoding="utf-8") as f:
        payload = json.load(f)

    symbols = {}
    excluded = {}
    aggregate = {
        period: {"baseline": [], "filtered": []}
        for period in PERIODS
    }
    aggregate_rules = {
        period: {
            rule: {"baseline": [], "filtered": []}
            for rule in VARIANTS
        } for period in PERIODS
    }
    total_candidate_counts = defaultdict(int)
    total_events = defaultdict(lambda: {"eligible_episodes": 0, "allowed_episodes": 0, "blocked_episodes": 0})
    total_scopes = defaultdict(int)

    for ticker, obj in payload.get("symbols", {}).items():
        bars, quality = clean_bars(obj["candles"])
        if len(bars) < MIN_BARS:
            excluded[ticker] = {"bars": len(bars), "reason": "MIN_BARS", "data_quality": quality}
            continue
        result = evaluate_ticker(ticker, bars)
        symbols[ticker] = {
            "status": "OK", "bars": len(bars), "data_quality": quality,
            "evaluation_start": result["evaluation_start"],
            "holdout_start": result["holdout_start"], "data_end": result["data_end"],
        }
        for rule, count in result["candidate_trade_counts"].items():
            total_candidate_counts[rule] += count
        for period in PERIODS:
            p = result["periods"][period]
            total_events[period]["eligible_episodes"] += p["eligible_episodes"]
            total_events[period]["allowed_episodes"] += p["allowed_episodes"]
            total_events[period]["blocked_episodes"] += p["blocked_episodes"]
            # Recreate pooled per-period trade lists from per-rule stats is not
            # possible; aggregate lists are assembled by rerunning the deterministic
            # ticker evaluator's stored rule summaries below.
            for rule in VARIANTS:
                rp = result["per_rule"][period][rule]
                # Store trade metrics rather than combine trade lists into a
                # misleading portfolio-like compounded series.
                aggregate_rules[period][rule]["baseline"].append(rp["baseline"])
                aggregate_rules[period][rule]["filtered"].append(rp["filtered"])
        for scope, count in result["gate_scope_counts"].items():
            total_scopes[scope] += count

    def combine_rule_metrics(items):
        # Equal-weight ticker summary; never compound across tickers.
        active = [x for x in items if x["trades"] > 0]
        means5 = [x["5bps"]["mean_net_return_pct"] for x in active]
        means10 = [x["10bps"]["mean_net_return_pct"] for x in active]
        pfs5 = [x["5bps"]["profit_factor"] for x in active if isinstance(x["5bps"]["profit_factor"], (int, float))]
        return {
            "ticker_trade_count_sum": sum(x["trades"] for x in items),
            "tickers_with_trades": len(active),
            "tickers_positive_mean_5bps": sum(x > 0 for x in means5),
            "mean_ticker_mean_net_5bps_pct": statistics.fmean(means5) if means5 else None,
            "median_ticker_mean_net_5bps_pct": statistics.median(means5) if means5 else None,
            "mean_ticker_mean_net_10bps_pct": statistics.fmean(means10) if means10 else None,
            "mean_ticker_profit_factor_5bps": statistics.fmean(pfs5) if pfs5 else None,
        }

    for period in PERIODS:
        for rule in VARIANTS:
            aggregate_rules[period][rule] = {
                "baseline": combine_rule_metrics(aggregate_rules[period][rule]["baseline"]),
                "filtered": combine_rule_metrics(aggregate_rules[period][rule]["filtered"]),
            }

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "data_source": "Finam technical H1 archive",
        "symbols_evaluated": len(symbols),
        "symbols_excluded": excluded,
        "protocol": {
            "purpose": "Test whether a causal market-suitability gate can block market episodes that have historically been unsuitable for the predeclared candidate signals. This is not a strategy selector.",
            "episode_definition": "One ticker/H1 signal close with one or more of six predeclared candidate rules. Episode outcome is the equal-weight mean gross return of its active candidate trades; this is a diagnostic market-condition label, not a portfolio return.",
            "causality": "An episode is added to training only after all candidate trades in that episode have exited strictly before the current signal bar. No current or future episode outcome is visible to the gate.",
            "gate": "Rolling latest 100 completed episodes per ticker/regime key; minimum 30. Backoff: joint trend+volatility, trend-only, volatility-only, then all regimes. Allow only if mean net episode return after 10 bps per side is positive and PF > 1.0; otherwise no trade.",
            "regime": "Ticker-specific causal trend-strength and ATR/close volatility ranks. Each metric is ranked against up to 120 prior observations, excluding current; at least 60 prior observations; low/mid/high terciles.",
            "execution": "Signal on completed H1 close; next H1 open entry; close after at most 12 H1 bars. Candidate streams are non-overlapping within each ticker/rule. Filter decision is common to all candidate rules firing at the same ticker/H1 close.",
            "walk_forward": "First half of first 80% is warm-up; remaining first 80% split into three chronological development folds; final 20% separately. Gate state carries forward using only prior completed episodes.",
            "costs": "Gate training threshold: 10 bps per side. Reported trade metrics: 5 and 10 bps per side, illustrative only.",
            "overlap_note": "Different strategy streams may overlap. Per-rule results are reported as independent diagnostic streams; pooled multi-rule trade chains are deliberately not presented as portfolio performance."
        },
        "aggregate_per_rule": aggregate_rules,
        "activity_by_period": {
            period: {
                **total_events[period],
                "blocked_episode_pct": (
                    total_events[period]["blocked_episodes"] /
                    total_events[period]["eligible_episodes"] * 100
                    if total_events[period]["eligible_episodes"] else None
                ),
            } for period in PERIODS
        },
        "gate_scope_counts": dict(total_scopes),
        "candidate_trade_counts": dict(total_candidate_counts),
        "symbols": symbols,
        "limitations": [
            "Diagnostic only: the same historical archive and final 20% have been examined in previous experiments; this is not independent confirmation.",
            "The episode suitability label averages the outcomes of whichever candidate strategies fired; it is a research proxy, not a tradable benchmark or portfolio return.",
            "The six candidate strategies are correlated and can overlap across rules; per-rule streams are not a combined portfolio.",
            "Ticker-specific regimes are not a common MOEX-wide market regime.",
            "Actual spread, commissions, slippage, borrow availability/cost, taxes and market impact are not modeled; 5/10 bps per side are illustrative.",
            "Finam H1 bars are technical data; 12 bars are not necessarily 12 clock hours.",
            "Research only: no production, real signals, Telegram notifications, cron changes, secrets or broker orders."
        ]
    }
    out = ROOT / "reports"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = out / f"market-suitability-gate-{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "OK", "symbols_evaluated": len(symbols),
        "activity_by_period": report["activity_by_period"],
        "gate_scope_counts": dict(total_scopes),
        "candidate_trade_counts": dict(total_candidate_counts),
        "report": str(report_path)
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
