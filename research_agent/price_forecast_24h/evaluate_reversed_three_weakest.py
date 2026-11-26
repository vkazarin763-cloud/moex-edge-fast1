"""Reverse the three weakest predeclared H1 entry rules; research only."""
from __future__ import annotations
import gzip, json
from datetime import datetime, timezone
from research_agent.price_forecast_24h.evaluate_direction_mechanics import (
    ROOT, MIN_BARS, HOLDOUT_FRAC, indicators, make_signals, run_window, summarize,
)

# Selected by the previously reported final-20% mean net return at 5 bps/side.
# The holdout has already been inspected; this is a diagnostic comparison, not
# a fresh confirmatory test. No rule or threshold is retuned here.
RULES = (
    "long_ema20_pullback",
    "short_momentum_10",
    "short_ema20_failed_bounce",
)

def main():
    data = ROOT / "data" / "H1_HISTORY.json.gz"
    with gzip.open(data, "rt", encoding="utf-8") as f:
        payload = json.load(f)

    pooled = {
        rule: {
            side: {"development": [], "holdout": [], "folds": {1: [], 2: [], 3: []}}
            for side in ("original", "reversed")
        }
        for rule in RULES
    }
    symbols = {}
    for ticker, obj in payload.get("symbols", {}).items():
        bars, quality = __import__(
            "research_agent.price_forecast_24h.evaluate_ohlc_strategies",
            fromlist=["clean_bars"],
        ).clean_bars(obj["candles"])
        if len(bars) < MIN_BARS:
            symbols[ticker] = {"status": "INSUFFICIENT", "bars": len(bars), **quality}
            continue

        ema, sma, _ = indicators(bars)
        all_signals = make_signals(bars, ema, sma)
        cutoff = int(len(bars) * (1 - HOLDOUT_FRAC))
        dev_start = int(cutoff * 0.50)
        width = (cutoff - dev_start) // 3
        folds = [
            (dev_start + k * width, cutoff if k == 2 else dev_start + (k + 1) * width)
            for k in range(3)
        ]
        per_rule = {}
        for rule in RULES:
            signal = all_signals[rule]
            reversed_signal = [-direction for direction in signal]
            variants = {}
            for side, series in (("original", signal), ("reversed", reversed_signal)):
                dev_trades = []
                fold_reports = {}
                for fold_no, (start, end) in enumerate(folds, 1):
                    trades = run_window(bars, series, start, end)
                    dev_trades.extend(trades)
                    pooled[rule][side]["folds"][fold_no].extend(trades)
                    fold_reports[str(fold_no)] = summarize(trades)
                holdout_trades = run_window(bars, series, cutoff, len(bars))
                pooled[rule][side]["development"].extend(dev_trades)
                pooled[rule][side]["holdout"].extend(holdout_trades)
                variants[side] = {
                    "development": summarize(dev_trades),
                    "development_folds": fold_reports,
                    "holdout": summarize(holdout_trades),
                }
            per_rule[rule] = variants

        symbols[ticker] = {
            "status": "OK",
            "bars": len(bars),
            "holdout_start": bars[cutoff]["timestamp"],
            "holdout_end": bars[-1]["timestamp"],
            "rules": per_rule,
            **quality,
        }

    aggregate = {}
    for rule in RULES:
        aggregate[rule] = {}
        for side in ("original", "reversed"):
            p = pooled[rule][side]
            aggregate[rule][side] = {
                "development": summarize(p["development"]),
                "development_folds": {
                    str(k): summarize(v) for k, v in p["folds"].items()
                },
                "holdout": summarize(p["holdout"]),
            }

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Finam technical H1 archive",
        "selected_rules": list(RULES),
        "selection_basis": "Three lowest final-20% mean net returns at 5 bps/side among six predeclared direction-specific rules in direction-specific-entry-mechanics-20261126T025634Z.json.",
        "protocol": (
            "For each rule, use exactly its original signal timestamps and next-H1-open "
            "entries / fixed 12-H1-bar close exits. Reversed version changes only "
            "direction (+1 to -1 or -1 to +1); no reselection. First 80% split into "
            "three chronological development folds; final 20% reported separately. "
            "Costs are 5 and 10 bps per side."
        ),
        "aggregate": aggregate,
        "symbols_evaluated": sum(v.get("status") == "OK" for v in symbols.values()),
        "symbols": symbols,
        "limitations": [
            "The final 20% was already inspected when selecting these three rules; this is diagnostic, not independent confirmation.",
            "Same historical Finam technical H1 archive; no external validation.",
            "Actual spreads, commissions, slippage, borrow availability/cost and taxes are not modeled; costs are illustrative.",
            "Short selling may not be available for every instrument.",
            "Pooled compounded trade-chain return is not a realizable portfolio return.",
            "Research only; no production changes, live signals, Telegram messages or broker orders.",
        ],
    }
    out = ROOT / "reports"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"reversed-three-weakest-{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    print(json.dumps({
        "status": "OK",
        "report": str(path),
        "symbols_evaluated": report["symbols_evaluated"],
        "aggregate": aggregate,
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
