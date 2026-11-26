"""Research-only trailing volatility-regime filters for breakout/SMA50 signals.

Filters are evaluated at signal close using ATR14/close percentile versus the
preceding 60 valid observations only (current observation excluded). Entry is
next-bar open; time exit after 12 H1 bars. No stops, overlap, holdout tuning,
or production integration.
"""
from __future__ import annotations
import gzip, json, math, statistics
from datetime import datetime, timezone
from pathlib import Path
from research_agent.price_forecast_24h.evaluate_ohlc_strategies import clean_bars, stats
from research_agent.price_forecast_24h.evaluate_atr_risk_controls import calc_atr, make_signals

ROOT=Path("research_agent/price_forecast_24h")
COSTS=(5,10)
HOLDOUT_FRAC=.20
FOLDS=3
ATR_LOOKBACK=60
MIN_HISTORY=30
MAX_HOLD=12
VARIANTS=("baseline","vol_rank_le_80","vol_rank_le_90","vol_rank_20_to_80")

def volatility_ranks(bars, atr):
    values=[(atr[i]/bars[i]["close"]) if atr[i] is not None and bars[i]["close"]>0 else None for i in range(len(bars))]
    ranks=[None]*len(bars)
    for i,x in enumerate(values):
        prior=[v for v in values[max(0,i-ATR_LOOKBACK):i] if v is not None]
        if x is not None and len(prior)>=MIN_HISTORY:
            ranks[i]=sum(v<=x for v in prior)/len(prior)
    return values,ranks

def allowed(variant, rank):
    if variant=="baseline": return True
    if rank is None: return False
    if variant=="vol_rank_le_80": return rank<=.80
    if variant=="vol_rank_le_90": return rank<=.90
    if variant=="vol_rank_20_to_80": return .20<=rank<=.80
    raise ValueError(variant)

def evaluate_symbol(rows):
    bars,q=clean_bars(rows)
    if len(bars)<400: return {"status":"INSUFFICIENT","bars":len(bars),**q}
    atr=calc_atr(bars); signals=make_signals(bars)
    vol,rank=volatility_ranks(bars,atr)
    cutoff=int(len(bars)*(1-HOLDOUT_FRAC)); first=int(cutoff*.50); width=(cutoff-first)//FOLDS
    folds=[(first+k*width,cutoff if k==FOLDS-1 else first+(k+1)*width) for k in range(FOLDS)]
    results={v:[] for v in VARIANTS}; opportunities={v:0 for v in VARIANTS}
    foldmeta=[]
    for fi,(a,b) in enumerate(folds,1):
        foldmeta.append({"fold":fi,"from":bars[a]["timestamp"],"to":bars[b-1]["timestamp"],"bars":b-a})
        for variant in VARIANTS:
            i=a
            while i<b-1:
                if signals[i]:
                    if allowed(variant,rank[i]):
                        opportunities[variant]+=1
                        entry_i=i+1
                        if entry_i<b:
                            entry=bars[entry_i]["open"]; exit_i=min(b-1,entry_i+MAX_HOLD-1)
                            exit_price=bars[exit_i]["close"]; direction=signals[i]
                            gross=direction*math.log(exit_price/entry)
                            results[variant].append({"entry_time":bars[entry_i]["timestamp"],
                              "exit_time":bars[exit_i]["timestamp"],"direction":"LONG" if direction==1 else "SHORT",
                              "entry_price":entry,"exit_price":exit_price,"gross_return":gross,
                              "holding_bars":exit_i-entry_i+1,"exit_index":exit_i,"exit_reason":"time",
                              "variant":variant,"signal_volatility_pct":vol[i]*100 if vol[i] is not None else None,
                              "signal_volatility_rank":rank[i]})
                            i=exit_i+1
                        else: i+=1
                    else: i+=1
                else: i+=1
    return {"status":"OK","bars":len(bars),"development_end":bars[cutoff-1]["timestamp"],
      "folds":foldmeta,"trades":results,"eligible_signals":opportunities,**q}

def main():
    with gzip.open(ROOT/"data"/"H1_HISTORY.json.gz","rt",encoding="utf-8") as f: payload=json.load(f)
    per={t:evaluate_symbol(x["candles"]) for t,x in payload.get("symbols",{}).items()}
    valid={t:v for t,v in per.items() if v.get("status")=="OK"}
    summary={}
    for variant in VARIANTS:
        summary[variant]={}
        for cost in COSTS:
            ts=[t for v in valid.values() for t in v["trades"][variant]]
            by=[stats(v["trades"][variant],cost) for v in valid.values() if v["trades"][variant]]
            s=stats(ts,cost);s["tickers_with_trades"]=len(by)
            s["tickers_positive"]=sum(x["total_compounded_return_pct"]>0 for x in by)
            s["median_ticker_compounded_return_pct"]=statistics.median(x["total_compounded_return_pct"] for x in by) if by else None
            s["eligible_signals"]=sum(v["eligible_signals"][variant] for v in valid.values())
            summary[variant][str(cost)]=s
    report={"created_utc":datetime.now(timezone.utc).isoformat(),"data_source":"Finam technical H1 archive",
      "design":"20-bar breakout + SMA50 direction and slope; next-bar open entry; fixed 12-bar time exit; non-overlapping trades; first 80% split into 3 chronological development folds; final 20% untouched.",
      "volatility_definition":"ATR14/close at signal close; empirical percentile rank versus up to preceding 60 valid ATR% observations, excluding current observation; at least 30 prior observations required for filtered variants.",
      "variants":VARIANTS,"atr_period":14,"lookback_bars":ATR_LOOKBACK,"minimum_prior_observations":MIN_HISTORY,
      "max_holding_bars":MAX_HOLD,"costs_bps_each_side":COSTS,"summary":summary,"symbols":per,
      "limitations":["same archived dataset; not independent fresh data","filters evaluated on development folds only; no final-20% holdout use","fees, real spread, slippage, borrow and taxes not modeled; costs illustrative","technical Finam H1 data; no production signals or deployment"]}
    out=ROOT/"reports";out.mkdir(parents=True,exist_ok=True)
    path=out/f"volatility-regime-filters-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":"OK","tickers":len(valid),"summary":summary,"report":str(path)},ensure_ascii=False))
if __name__=="__main__": main()
