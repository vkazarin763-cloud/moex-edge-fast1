"""Diagnostic regime attribution for six predeclared H1 LONG/SHORT rules.

Regimes are causal trailing ranks at signal close: absolute 5-bar SMA50 slope
and ATR14/close, each ranked against up to 120 prior valid observations
(excluding current). Tercile boundaries are fixed at 1/3 and 2/3.
Research only; no threshold search or production integration.
"""
from __future__ import annotations
import gzip, json, math, statistics
from datetime import datetime, timezone
from pathlib import Path

from research_agent.price_forecast_24h.evaluate_direction_mechanics import (
    ROOT, MIN_BARS, HOLDOUT_FRAC, indicators, make_signals, VARIANTS
)
from research_agent.price_forecast_24h.evaluate_ohlc_strategies import clean_bars, stats

LOOKBACK = 120
MIN_PRIOR = 60
MAX_HOLD = 12
COSTS = (5, 10)
BINS = ("low", "mid", "high")
PERIODS = ("development_fold_1", "development_fold_2", "development_fold_3", "holdout")
SIDES = ("original", "reversed")

def trailing_rank(values, i):
    current = values[i]
    if current is None:
        return None
    prior = [x for x in values[max(0, i-LOOKBACK):i] if x is not None]
    if len(prior) < MIN_PRIOR:
        return None
    return sum(x <= current for x in prior) / len(prior)

def tercile(rank):
    if rank is None:
        return "unclassified"
    if rank <= 1/3:
        return "low"
    if rank <= 2/3:
        return "mid"
    return "high"

def build_regimes(bars, sma, atr):
    slope = [None] * len(bars)
    vol = [None] * len(bars)
    for i in range(len(bars)):
        if sma[i] is not None and i >= 5 and sma[i-5] is not None and sma[i-5] > 0:
            slope[i] = abs(sma[i] / sma[i-5] - 1.0)
        if atr[i] is not None and bars[i]["close"] > 0:
            vol[i] = atr[i] / bars[i]["close"]
    out=[]
    for i in range(len(bars)):
        sr=trailing_rank(slope,i)
        vr=trailing_rank(vol,i)
        out.append({
            "trend_strength": tercile(sr),
            "volatility": tercile(vr),
            "trend_rank": sr,
            "volatility_rank": vr,
        })
    return out

def run_segment(bars, signals, regimes, start, end, ticker, rule, side, period):
    trades=[]
    i=start
    while i<end-1:
        direction=signals[i]
        if not direction:
            i+=1
            continue
        entry_i=i+1
        if entry_i>=end:
            break
        exit_i=min(end-1, entry_i+MAX_HOLD-1)
        entry=bars[entry_i]["open"]
        exitp=bars[exit_i]["close"]
        if entry>0 and exitp>0:
            if side=="reversed":
                direction=-direction
            trades.append({
                "ticker":ticker,
                "rule":rule,
                "side":side,
                "period":period,
                "signal_time":bars[i]["timestamp"],
                "entry_time":bars[entry_i]["timestamp"],
                "exit_time":bars[exit_i]["timestamp"],
                "direction":"LONG" if direction==1 else "SHORT",
                "entry_price":entry,
                "exit_price":exitp,
                "gross_return":direction*math.log(exitp/entry),
                "holding_bars":exit_i-entry_i+1,
                "trend_strength_regime":regimes[i]["trend_strength"],
                "volatility_regime":regimes[i]["volatility"],
                "trend_rank":regimes[i]["trend_rank"],
                "volatility_rank":regimes[i]["volatility_rank"],
            })
        i=exit_i+1
    return trades

def metric(trades):
    s5=stats(trades,5); s10=stats(trades,10)
    return {
        "trades":len(trades),
        "5bps":{k:s5[k] for k in ("win_rate_pct","mean_net_return_pct","median_net_return_pct","profit_factor","max_drawdown_pct")},
        "10bps":{k:s10[k] for k in ("win_rate_pct","mean_net_return_pct","profit_factor","max_drawdown_pct")},
    }

def summarize_groups(trades, group_key):
    result={}
    keys=sorted({t[group_key] for t in trades})
    for key in keys:
        result[key]=metric([t for t in trades if t[group_key]==key])
    return result

def main():
    path=ROOT/"data"/"H1_HISTORY.json.gz"
    if not path.exists():
        raise SystemExit("H1_HISTORY.json.gz missing")
    with gzip.open(path,"rt",encoding="utf-8") as f:
        payload=json.load(f)

    pooled={rule:{side:[] for side in SIDES} for rule in VARIANTS}
    symbol_count=0
    excluded={}
    for ticker,obj in payload.get("symbols",{}).items():
        bars,quality=clean_bars(obj["candles"])
        if len(bars)<MIN_BARS:
            excluded[ticker]={"bars":len(bars),"reason":"MIN_BARS","quality":quality}
            continue
        symbol_count+=1
        ema,sma,atr=indicators(bars)
        regimes=build_regimes(bars,sma,atr)
        signals=make_signals(bars,ema,sma)
        cutoff=int(len(bars)*(1-HOLDOUT_FRAC))
        dev_start=int(cutoff*.50)
        width=(cutoff-dev_start)//3
        folds=[
            (dev_start+k*width, cutoff if k==2 else dev_start+(k+1)*width)
            for k in range(3)
        ]
        for rule in VARIANTS:
            for side in SIDES:
                for fold_no,(a,b) in enumerate(folds,1):
                    period=f"development_fold_{fold_no}"
                    pooled[rule][side].extend(
                        run_segment(bars,signals[rule],regimes,a,b,ticker,rule,side,period)
                    )
                pooled[rule][side].extend(
                    run_segment(bars,signals[rule],regimes,cutoff,len(bars),ticker,rule,side,"holdout")
                )

    report_rules={}
    for rule in VARIANTS:
        report_rules[rule]={}
        for side in SIDES:
            trades=pooled[rule][side]
            by_period={}
            for period in PERIODS:
                subset=[t for t in trades if t["period"]==period]
                by_period[period]={
                    "overall":metric(subset),
                    "trend_strength":summarize_groups(subset,"trend_strength_regime"),
                    "volatility":summarize_groups(subset,"volatility_regime"),
                    "joint_trend_volatility":{
                        f"{trend}|{vol}":metric([
                            t for t in subset
                            if t["trend_strength_regime"]==trend and t["volatility_regime"]==vol
                        ])
                        for trend in BINS for vol in BINS
                        if any(t["trend_strength_regime"]==trend and t["volatility_regime"]==vol for t in subset)
                    },
                }
            report_rules[rule][side]=by_period

    report={
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "data_source":"Finam technical H1 archive",
        "symbols_evaluated":symbol_count,
        "symbols_excluded":excluded,
        "rules":list(VARIANTS),
        "protocol":{
            "entry":"signal on completed H1 close; entry next H1 open",
            "exit":"close after fixed 12 H1 bars; non-overlapping per ticker/rule/side",
            "regime_attribution":"Regime measured at signal close. Trend strength is absolute 5-bar percentage slope of SMA50; volatility is ATR14/close. Each is ranked against up to 120 prior valid observations for that ticker, excluding current observation; at least 60 prior observations required. Relative ranks split into low/mid/high terciles.",
            "periods":"first 80% split into three chronological development folds; final 20% holdout shown separately",
            "costs_bps_each_side":list(COSTS),
            "reversed":"For diagnostic comparison, same signal times and exits with direction flipped; no re-selection or threshold tuning."
        },
        "aggregate":report_rules,
        "limitations":[
            "Diagnostic subgroup analysis on the same historical archive; holdout has already been examined in prior experiments and is not a fresh confirmatory sample.",
            "Relative regimes are ticker-specific, not a common market-wide regime.",
            "Tercile subgroup results can be noisy; small sample sizes must not be treated as proof.",
            "Actual spread, commissions, slippage, borrow availability/cost and taxes are not modeled; 5/10 bps per side are illustrative.",
            "Finam H1 candles are technical data; 12 bars are not necessarily 12 clock hours.",
            "Pooled trade-chain statistics are not portfolio returns.",
            "Research only: no production, live signals, Telegram notifications or broker orders."
        ]
    }
    out=ROOT/"reports"
    out.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path=out/f"market-regime-attribution-{stamp}.json"
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    compact={}
    for rule in VARIANTS:
        compact[rule]={}
        for side in SIDES:
            compact[rule][side]={}
            for period in PERIODS:
                p=report_rules[rule][side][period]
                compact[rule][side][period]={
                    "overall":p["overall"],
                    "trend_strength":p["trend_strength"],
                    "volatility":p["volatility"],
                }
    print(json.dumps({
        "status":"OK",
        "symbols_evaluated":symbol_count,
        "report":str(report_path),
        "summary":compact
    },ensure_ascii=False))

if __name__=="__main__":
    main()
