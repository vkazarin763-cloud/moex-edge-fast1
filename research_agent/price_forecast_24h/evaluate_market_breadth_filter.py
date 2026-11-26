"""Research-only MOEX-wide H1 breadth filter.

Uses exact UTC-normalized H1 timestamps only: no forward fill or future bars.
A breadth observation is eligible only when at least 30 universe members have
both a valid SMA50 and a 5-bar return at that exact timestamp. LONG signals
pass only in broad-positive conditions; SHORT signals pass only in broad-
negative conditions. Fixed thresholds are predeclared, not optimized.
"""
from __future__ import annotations
import gzip, json, math, statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone

from research_agent.price_forecast_24h.evaluate_direction_mechanics import (
    ROOT, MIN_BARS, HOLDOUT_FRAC, indicators, make_signals, VARIANTS
)
from research_agent.price_forecast_24h.evaluate_ohlc_strategies import clean_bars, stats

MAX_HOLD = 12
COSTS = (5, 10)
MIN_BREADTH_COVERAGE = 30
MIN_BREADTH_COVERAGE_PCT = 0.68
ABOVE_SMA_LONG_MIN = 0.55
ADVANCERS_5D_LONG_MIN = 0.60
BELOW_SMA_SHORT_MIN = 0.55
DECLINERS_5D_SHORT_MIN = 0.60
PERIODS = ("development_fold_1", "development_fold_2", "development_fold_3", "holdout")


def utc_key(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        # Preserve naive timestamps as a distinct clock convention; all source
        # bars are expected to use one convention. Never infer a timezone.
        return dt.isoformat()
    return dt.astimezone(timezone.utc).isoformat()


def prepare_symbols(payload):
    prepared = {}
    excluded = {}
    for ticker, obj in payload.get("symbols", {}).items():
        bars, quality = clean_bars(obj["candles"])
        if len(bars) < MIN_BARS:
            excluded[ticker] = {"bars_after_cleaning": len(bars), "reason": "MIN_BARS", "quality": quality}
            continue
        ema, sma, atr = indicators(bars)
        signals = make_signals(bars, ema, sma)
        rows = []
        for i, bar in enumerate(bars):
            sma50 = sma[i]
            ret5 = (bar["close"] / bars[i-5]["close"] - 1.0) if i >= 5 and bars[i-5]["close"] > 0 else None
            ret1 = (bar["close"] / bars[i-1]["close"] - 1.0) if i >= 1 and bars[i-1]["close"] > 0 else None
            rows.append({
                "timestamp": bar["timestamp"],
                "utc_key": utc_key(bar["timestamp"]),
                "sma50": sma50,
                "above_sma50": (bar["close"] > sma50) if sma50 is not None else None,
                "return_5": ret5,
                "return_1": ret1,
            })
        prepared[ticker] = {
            "bars": bars, "signals": signals, "quality": quality, "breadth_rows": rows
        }
    return prepared, excluded


def build_breadth(prepared):
    at_time = defaultdict(list)
    for ticker, obj in prepared.items():
        for row in obj["breadth_rows"]:
            if row["sma50"] is not None and row["return_5"] is not None:
                at_time[row["utc_key"]].append({
                    "ticker": ticker,
                    "above": row["above_sma50"],
                    "ret5": row["return_5"],
                    "ret1": row["return_1"],
                })

    breadth = {}
    coverage_hist = Counter()
    total_symbol_bars = 0
    matched_symbol_bars = 0
    valid_timestamps = 0
    for key, rows in at_time.items():
        coverage = len(rows)
        coverage_hist[str(coverage)] += 1
        total_symbol_bars += coverage
        if coverage < MIN_BREADTH_COVERAGE:
            continue
        valid_timestamps += 1
        matched_symbol_bars += coverage
        above = sum(x["above"] for x in rows) / coverage
        below = 1.0 - above
        adv5 = sum(x["ret5"] > 0 for x in rows) / coverage
        dec5 = sum(x["ret5"] < 0 for x in rows) / coverage
        valid_ret1 = [x["ret1"] for x in rows if x["ret1"] is not None]
        adv1 = sum(x > 0 for x in valid_ret1) / len(valid_ret1) if valid_ret1 else None
        dec1 = sum(x < 0 for x in valid_ret1) / len(valid_ret1) if valid_ret1 else None
        positive = (
            above >= ABOVE_SMA_LONG_MIN and adv5 >= ADVANCERS_5D_LONG_MIN
        )
        negative = (
            below >= BELOW_SMA_SHORT_MIN and dec5 >= DECLINERS_5D_SHORT_MIN
        )
        breadth[key] = {
            "coverage": coverage,
            "above_sma50_pct": above * 100,
            "below_sma50_pct": below * 100,
            "advancers_5bar_pct": adv5 * 100,
            "decliners_5bar_pct": dec5 * 100,
            "advancers_1bar_pct": adv1 * 100 if adv1 is not None else None,
            "decliners_1bar_pct": dec1 * 100 if dec1 is not None else None,
            "state": "positive" if positive else ("negative" if negative else "neutral"),
        }

    all_symbol_bars = sum(len(x["bars"]) for x in prepared.values())
    # This is a strict exact-timestamp coverage ratio, not an as-of estimate.
    exact_coverage_pct = matched_symbol_bars / all_symbol_bars * 100 if all_symbol_bars else 0.0
    coverage_values = [x["coverage"] for x in breadth.values()]
    alignment = {
        "timestamp_keys_with_any_eligible_constituents": len(at_time),
        "timestamp_keys_passing_min_coverage": valid_timestamps,
        "minimum_coverage_symbols": MIN_BREADTH_COVERAGE,
        "universe_symbols_evaluated": len(prepared),
        "eligible_timestamp_coverage_min": min(coverage_values) if coverage_values else None,
        "eligible_timestamp_coverage_median": statistics.median(coverage_values) if coverage_values else None,
        "eligible_timestamp_coverage_max": max(coverage_values) if coverage_values else None,
        "exact_timestamp_matched_symbol_bars_pct": exact_coverage_pct,
        "coverage_distribution_by_symbol_count": dict(sorted(coverage_hist.items(), key=lambda x: int(x[0]))),
        "alignment_policy": "Exact normalized UTC timestamp only; no forward fill, interpolation, nearest/as-of join, or future data. Naive timestamps retain their naive clock convention and are not mixed with timezone-aware timestamps.",
    }
    return breadth, alignment


def split_bounds(n):
    cutoff = int(n * (1 - HOLDOUT_FRAC))
    eval_start = int(cutoff * 0.50)
    width = (cutoff - eval_start) // 3
    folds = [
        (eval_start + k * width, cutoff if k == 2 else eval_start + (k + 1) * width)
        for k in range(3)
    ]
    return cutoff, eval_start, folds


def period_name(i, cutoff, folds):
    if i >= cutoff:
        return "holdout"
    for no, (start, end) in enumerate(folds, 1):
        if start <= i < end:
            return f"development_fold_{no}"
    return "warmup"


def simulate_segment(ticker, bars, signals, breadth, rule, start, end, period):
    baseline = []
    filtered = []
    skipped = Counter()
    i = start
    while i < end - 1:
        direction = signals[i]
        if not direction:
            i += 1
            continue
        signal_key = utc_key(bars[i]["timestamp"])
        market = breadth.get(signal_key)
        if market is None:
            skipped["missing_or_low_coverage"] += 1
            # A blocked candidate does not consume a position slot.
            i += 1
            continue

        entry_i = i + 1
        if entry_i >= end:
            break
        exit_i = min(end - 1, entry_i + MAX_HOLD - 1)
        entry = bars[entry_i]["open"]
        exit_price = bars[exit_i]["close"]
        if entry <= 0 or exit_price <= 0:
            i += 1
            continue
        trade = {
            "ticker": ticker,
            "rule": rule,
            "period": period,
            "signal_time": bars[i]["timestamp"],
            "entry_time": bars[entry_i]["timestamp"],
            "exit_time": bars[exit_i]["timestamp"],
            "direction": "LONG" if direction == 1 else "SHORT",
            "gross_return": direction * math.log(exit_price / entry),
            "holding_bars": exit_i - entry_i + 1,
            "breadth_state": market["state"],
            "breadth_coverage": market["coverage"],
            "above_sma50_pct": market["above_sma50_pct"],
            "below_sma50_pct": market["below_sma50_pct"],
            "advancers_5bar_pct": market["advancers_5bar_pct"],
            "decliners_5bar_pct": market["decliners_5bar_pct"],
        }
        baseline.append(trade)
        allow = (
            (direction == 1 and market["state"] == "positive")
            or (direction == -1 and market["state"] == "negative")
        )
        if allow:
            filtered.append(trade)
        else:
            skipped[f"breadth_{market['state']}"] += 1
        # Same candidate stream mechanics in baseline and filtered:
        # a signal occupies the ticker/rule stream for up to 12 bars,
        # whether or not the breadth gate permits the trade.
        i = exit_i + 1
    return baseline, filtered, skipped


def metric_summary(trades):
    result = {}
    for cost in COSTS:
        result[str(cost)] = stats(trades, cost)
    return {
        "trades": len(trades),
        "long_trades": sum(t["direction"] == "LONG" for t in trades),
        "short_trades": sum(t["direction"] == "SHORT" for t in trades),
        "5bps": result["5"],
        "10bps": result["10"],
    }


def ticker_equal_weight_summary(by_ticker, cost_key):
    active = [v for v in by_ticker.values() if v["trades"] > 0]
    means = [v[cost_key]["mean_net_return_pct"] for v in active]
    pfs = [v[cost_key]["profit_factor"] for v in active
           if isinstance(v[cost_key]["profit_factor"], (int, float))]
    dds = [v[cost_key]["max_drawdown_pct"] for v in active
           if v[cost_key]["max_drawdown_pct"] is not None]
    return {
        "ticker_trade_count_sum": sum(v["trades"] for v in by_ticker.values()),
        "tickers_with_trades": len(active),
        "tickers_positive_mean": sum(x > 0 for x in means),
        "mean_ticker_mean_net_return_pct": statistics.fmean(means) if means else None,
        "median_ticker_mean_net_return_pct": statistics.median(means) if means else None,
        "mean_ticker_profit_factor": statistics.fmean(pfs) if pfs else None,
        "mean_ticker_max_drawdown_pct": statistics.fmean(dds) if dds else None,
    }


def main():
    data_path = ROOT / "data" / "H1_HISTORY.json.gz"
    if not data_path.exists():
        raise SystemExit("H1_HISTORY.json.gz missing")
    with gzip.open(data_path, "rt", encoding="utf-8") as f:
        payload = json.load(f)

    prepared, excluded = prepare_symbols(payload)
    if not prepared:
        raise SystemExit("No symbols passed minimum history requirement")
    breadth, alignment = build_breadth(prepared)

    symbol_reports = {}
    aggregate = {
        period: {
            rule: {"baseline": {}, "filtered": {}}
            for rule in VARIANTS
        } for period in PERIODS
    }
    skipped_total = Counter()
    state_counts = Counter()
    for x in breadth.values():
        state_counts[x["state"]] += 1

    for ticker, obj in prepared.items():
        bars, signals = obj["bars"], obj["signals"]
        cutoff, eval_start, folds = split_bounds(len(bars))
        per_period = {}
        for period in PERIODS:
            per_period[period] = {}
            if period == "holdout":
                start, end = cutoff, len(bars)
            else:
                no = int(period.rsplit("_", 1)[1]) - 1
                start, end = folds[no]
            for rule in VARIANTS:
                base, kept, skipped = simulate_segment(
                    ticker, bars, signals[rule], breadth, rule, start, end, period
                )
                per_period[period][rule] = {
                    "baseline": metric_summary(base),
                    "filtered": metric_summary(kept),
                    "skipped_candidate_signals": dict(skipped),
                }
                for key, value in skipped.items():
                    skipped_total[key] += value
                # Store only per-ticker metric summaries; do not concatenate
                # different tickers into a synthetic portfolio/trade chain.
                aggregate[period][rule]["baseline"][ticker] = metric_summary(base)
                aggregate[period][rule]["filtered"][ticker] = metric_summary(kept)

        symbol_reports[ticker] = {
            "status": "OK",
            "bars_after_cleaning": len(bars),
            "evaluation_start": bars[eval_start]["timestamp"],
            "holdout_start": bars[cutoff]["timestamp"],
            "data_end": bars[-1]["timestamp"],
            "data_quality": obj["quality"],
            "periods": per_period,
        }

    aggregate_summary = {}
    for period in PERIODS:
        aggregate_summary[period] = {}
        for rule in VARIANTS:
            base_by = aggregate[period][rule]["baseline"]
            filt_by = aggregate[period][rule]["filtered"]
            aggregate_summary[period][rule] = {
                "baseline": {
                    "5bps": ticker_equal_weight_summary(base_by, "5bps"),
                    "10bps": ticker_equal_weight_summary(base_by, "10bps"),
                },
                "filtered": {
                    "5bps": ticker_equal_weight_summary(filt_by, "5bps"),
                    "10bps": ticker_equal_weight_summary(filt_by, "10bps"),
                },
            }

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "data_source": "Finam technical H1 archive",
        "universe_size_in_source": len(payload.get("symbols", {})),
        "symbols_evaluated": len(prepared),
        "symbols_excluded": excluded,
        "timestamp_alignment": alignment,
        "breadth_state_timestamp_counts": dict(state_counts),
        "protocol": {
            "purpose": "Research whether a cross-sectional MOEX-wide breadth filter improves the six predeclared LONG/SHORT H1 strategy streams.",
            "breadth_definition": "At each exact timestamp, among symbols with valid SMA50 and 5-bar returns at that same timestamp: above_sma50_pct, below_sma50_pct, 5-bar advancers and decliners. One-bar advancers/decliners are also recorded for diagnostics.",
            "long_gate": f"Allow LONG only when at least {ABOVE_SMA_LONG_MIN:.0%} of covered symbols are above own SMA50 AND at least {ADVANCERS_5D_LONG_MIN:.0%} have positive 5-bar return.",
            "short_gate": f"Allow SHORT only when at least {BELOW_SMA_SHORT_MIN:.0%} of covered symbols are below own SMA50 AND at least {DECLINERS_5D_SHORT_MIN:.0%} have negative 5-bar return.",
            "coverage_gate": f"Require at least {MIN_BREADTH_COVERAGE} symbols with both SMA50 and 5-bar return at the exact timestamp; otherwise no trade.",
            "thresholds": "All thresholds fixed before evaluation; no optimization on development folds or holdout.",
            "execution": "Signal on completed H1 close; enter next H1 open; exit at close after at most 12 H1 bars. Non-overlapping stream per ticker/rule. Baseline and filtered use identical signal opportunities and stream occupancy; filtered trades are a subset of baseline.",
            "walk_forward": "Per ticker: first 50% of first 80% is warm-up; remaining first 80% split into three chronological development folds; final 20% evaluated separately. Indicators and breadth use current completed bar and prior data only.",
            "costs": "5 and 10 bps per side, illustrative only.",
            "aggregation": "Per-rule equal-weight ticker averages and per-ticker metrics. No combined multi-rule or cross-ticker compounded trade chain is represented as portfolio performance.",
            "holdout_status": "Diagnostic only: the same archive and final 20% have already been examined in prior experiments; this is not independent confirmation.",
        },
        "aggregate_per_rule": aggregate_summary,
        "skipped_candidate_signals": dict(skipped_total),
        "symbols": symbol_reports,
        "limitations": [
            "Finam technical H1 candles, not an exchange-certified synchronized MOEX index feed.",
            "Exact timestamp matching can reduce coverage; no stale-bar carry-forward is used. Timestamp coverage statistics are included.",
            "Naive timestamps retain their source clock convention; aware timestamps are normalized to UTC. Mixed naive/aware source timestamps are not joined.",
            "The 44-name universe may contain survivorship/composition bias.",
            "5/10 bps per side are illustrative; actual spreads, commissions, slippage, borrow availability/cost, taxes and market impact are not modeled.",
            "Final 20% is not an untouched independent validation sample because prior research has already inspected it.",
            "Research only: no production signals, Telegram, cron, secrets, Finam settings or broker orders changed.",
        ],
    }
    out = ROOT / "reports"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = out / f"market-breadth-filter-{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    compact = {
        period: {
            rule: {
                side: {
                    "5bps": aggregate_summary[period][rule][side]["5bps"],
                    "10bps": aggregate_summary[period][rule][side]["10bps"],
                } for side in ("baseline", "filtered")
            } for rule in VARIANTS
        } for period in PERIODS
    }
    print(json.dumps({
        "status": "OK",
        "symbols_evaluated": len(prepared),
        "timestamp_alignment": alignment,
        "breadth_state_timestamp_counts": dict(state_counts),
        "aggregate_per_rule": compact,
        "report": str(report_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
