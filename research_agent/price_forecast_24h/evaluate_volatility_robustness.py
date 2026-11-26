"""Robustness and untouched holdout validation for the preselected 20-80 ATR% rank filter.

The 20-80 filter is frozen before this evaluation. Reports LONG/SHORT, ticker,
and chronological development-fold breakdowns plus one final 20% holdout.
No parameter search or threshold changes occur here.
"""
from __future__ import annotations
import gzip,json,math,statistics
from datetime import datetime,timezone
from pathlib import Path
from research_agent.price_forecast_24h.evaluate_ohlc_strategies import clean_bars,stats
from research_agent.price_forecast_24h.evaluate_atr_risk_controls import calc_atr,make_signals
from research_agent.price_forecast_24h.evaluate_volatility_regimes import volatility_ranks,allowed

ROOT=Path("research_agent/price_forecast_24h")
COSTS=(5,10)
HOLDOUT_FRAC=.20
MAX_HOLD=12
VARIANTS=("baseline","vol_rank_20_to_80")

def run_window(bars,signals,vol,rank,start,end,variant):
    trades=[]; i=start
    while i<end-1:
        if signals[i] and allowed(variant,rank[i]):
            entry_i=i+1
            if entry_i<end:
                exit_i=min(end-1,entry_i+MAX_HOLD-1)
                entry=bars[entry_i]["open"]; exitp=bars[exit_i]["close"]; direction=signals[i]
                trades.append({"entry_time":bars[entry_i]["timestamp"],"exit_time":bars[exit_i]["timestamp"],
                  "direction":"LONG" if direction==1 else "SHORT","entry_price":entry,"exit_price":exitp,
                  "gross_return":direction*math.log(exitp/entry),"holding_bars":exit_i-entry_i+1,
                  "signal_volatility_pct":vol[i]*100 if vol[i] is not None else None,
                  "signal_volatility_rank":rank[i]})
                i=exit_i+1
            else:i+=1
        else:i+=1
    return trades

def summarize(trades):
    result={}
    for cost in COSTS:
        result[str(cost)]=stats(trades,cost)
    result["count"]=len(trades)
    result["long_count"]=sum(t["direction"]=="LONG" for t in trades)
    result["short_count"]=sum(t["direction"]=="SHORT" for t in trades)
    result["long"]={str(c):stats([t for t in trades if t["direction"]=="LONG"],c) for c in COSTS}
    result["short"]={str(c):stats([t for t in trades if t["direction"]=="SHORT"],c) for c in COSTS}
    return result

def main():
    with gzip.open(ROOT/"data"/"H1_HISTORY.json.gz","rt",encoding="utf-8") as f: payload=json.load(f)
    symbols={}; pooled={v:{"development":[],"holdout":[]} for v in VARIANTS}
    dev_fold_trades={v:{1:[],2:[],3:[]} for v in VARIANTS}
    for ticker,obj in payload.get("symbols",{}).items():
        bars,q=clean_bars(obj["candles"])
        if len(bars)<400:
            symbols[ticker]={"status":"INSUFFICIENT","bars":len(bars),**q};continue
        atr=calc_atr(bars);signals=make_signals(bars);vol,rank=volatility_ranks(bars,atr)
        cutoff=int(len(bars)*(1-HOLDOUT_FRAC)); first=int(cutoff*.50); width=(cutoff-first)//3
        folds=[(first+k*width,cutoff if k==2 else first+(k+1)*width) for k in range(3)]
        ticker_result={"status":"OK","bars":len(bars),"development_end":bars[cutoff-1]["timestamp"],
          "holdout_start":bars[cutoff]["timestamp"],"holdout_end":bars[-1]["timestamp"],"variants":{}}
        for variant in VARIANTS:
            dev=[]
            for fi,(a,b) in enumerate(folds,1):
                tr=run_window(bars,signals,vol,rank,a,b,variant)
                dev.extend(tr);dev_fold_trades[variant][fi].extend(tr)
            ho=run_window(bars,signals,vol,rank,cutoff,len(bars),variant)
            pooled[variant]["development"].extend(dev);pooled[variant]["holdout"].extend(ho)
            ticker_result["variants"][variant]={"development":summarize(dev),"holdout":summarize(ho)}
        symbols[ticker]=ticker_result
    aggregate={}
    for variant in VARIANTS:
        aggregate[variant]={"development":summarize(pooled[variant]["development"]),
          "holdout":summarize(pooled[variant]["holdout"]),
          "development_folds":{str(k):summarize(v) for k,v in dev_fold_trades[variant].items()}}
    report={"created_utc":datetime.now(timezone.utc).isoformat(),"data_source":"Finam technical H1 archive",
      "frozen_candidate":"vol_rank_20_to_80","candidate_definition":"ATR14/close empirical percentile rank between 20th and 80th inclusive versus preceding up to 60 valid observations, excluding current bar; minimum 30 prior observations.",
      "baseline":"20-bar breakout + SMA50 direction/slope; next-bar open entry; 12 H1 bar time exit; non-overlapping per ticker.",
      "holdout_protocol":"Final chronological 20% per ticker; no parameter selection, threshold adjustment, or model fitting on this segment. ATR percentile uses only preceding observations. Trades are entered and exited entirely inside the segment.",
      "costs_bps_each_side":COSTS,"max_holding_bars":MAX_HOLD,"aggregate":aggregate,"symbols":symbols,
      "limitations":["one archived data sample; not independent external validation","Finam H1 technical data; no live execution","fees, actual spread, slippage, borrow availability/cost and taxes omitted; costs illustrative","aggregate compounded returns across symbols are not a realizable portfolio return","holdout tested once after candidate preselection; further changes require new out-of-sample data"]}
    out=ROOT/"reports";out.mkdir(parents=True,exist_ok=True)
    path=out/f"volatility-filter-robustness-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":"OK","symbols":sum(x.get("status")=="OK" for x in symbols.values()),
      "aggregate":aggregate,"report":str(path)},ensure_ascii=False))
if __name__=="__main__":main()
