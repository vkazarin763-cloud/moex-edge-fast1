"""Research-only SMA50 breakout exit/filter robustness on pre-holdout chronological folds."""
from __future__ import annotations
import gzip,json,math,statistics
from datetime import datetime,timezone
from pathlib import Path
from research_agent.price_forecast_24h.evaluate_ohlc_strategies import clean_bars,indicators,stats,HORIZON

ROOT=Path("research_agent/price_forecast_24h")
COSTS=(5,10)
HOLDOUT_FRAC=.20
FOLDS=3
EXIT_HORIZONS=(12,24,36)
VARIANTS=("fixed_12","fixed_24","fixed_36","sma50_cross","sma50_slope_5bar")

def calc_trade(bars,signal_i,end,direction,exit_variant,sma50,mean):
    entry_i=signal_i+1
    if entry_i>=end:return None
    entry=bars[entry_i]["open"]
    max_hold=int(exit_variant.split("_")[-1]) if exit_variant.startswith("fixed_") else 36
    exit_i=min(end-1,entry_i+max_hold-1)
    if exit_variant=="sma50_cross":
        for j in range(entry_i,exit_i+1):
            if sma50[j] is not None and ((direction==1 and bars[j]["close"]<sma50[j]) or (direction==-1 and bars[j]["close"]>sma50[j])):
                exit_i=j;break
    exit_price=bars[exit_i]["close"]
    gross=direction*math.log(exit_price/entry)
    return {"entry_time":bars[entry_i]["timestamp"],"exit_time":bars[exit_i]["timestamp"],
      "direction":"LONG" if direction==1 else "SHORT","entry_price":entry,"exit_price":exit_price,
      "gross_return":gross,"holding_bars":exit_i-entry_i+1,"variant":exit_variant}

def signals(bars,variant):
    ph,pl,mean,sd,sma50,rsi=indicators(bars)
    n=len(bars);out=[0]*n
    for i in range(51,n):
        d=1 if ph[i] is not None and bars[i]["close"]>ph[i] else (-1 if pl[i] is not None and bars[i]["close"]<pl[i] else 0)
        if not d or sma50[i] is None:continue
        prev=statistics.fmean(x["close"] for x in bars[i-50:i])
        if d==1 and bars[i]["close"]>sma50[i] and sma50[i]>prev:out[i]=1
        elif d==-1 and bars[i]["close"]<sma50[i] and sma50[i]<prev:out[i]=-1
        if variant=="sma50_slope_5bar":
            if i<55:out[i]=0;continue
            past=statistics.fmean(x["close"] for x in bars[i-54:i-4])
            if (d==1 and sma50[i]<=past*1.001) or (d==-1 and sma50[i]>=past*.999):out[i]=0
    return out,sma50,mean

def eval_symbol(rows):
    bars,q=clean_bars(rows)
    if len(bars)<400:return {"status":"INSUFFICIENT","bars":len(bars),**q}
    cutoff=int(len(bars)*(1-HOLDOUT_FRAC))
    first=int(cutoff*.50);width=(cutoff-first)//FOLDS
    folds=[]
    for k in range(FOLDS):
        a=first+k*width;b=cutoff if k==FOLDS-1 else first+(k+1)*width
        if b-a>40:folds.append((a,b))
    result={v:[] for v in VARIANTS}
    foldmeta=[]
    # Signals are causal rolling indicators; only pre-final-20% data is scored.
    sig_cache={v:signals(bars,v) for v in VARIANTS}
    for fi,(a,b) in enumerate(folds,1):
        foldmeta.append({"fold":fi,"from":bars[a]["timestamp"],"to":bars[b-1]["timestamp"],"bars":b-a})
        for v,(sig,sma,mean) in sig_cache.items():
            i=a
            while i<b-1:
                if sig[i]:
                    t=calc_trade(bars,i,b,sig[i],v,sma,mean)
                    if t: t["fold"]=fi;result[v].append(t)
                    i+=HORIZON
                else:i+=1
    return {"status":"OK","bars":len(bars),"development_period_end":bars[cutoff-1]["timestamp"],
      "folds":foldmeta,"variants":{v:{str(c):stats(ts,c) for c in COSTS} for v,ts in result.items()},
      "trades":result,**q}

def main():
    with gzip.open(ROOT/"data"/"H1_HISTORY.json.gz","rt",encoding="utf-8") as f:payload=json.load(f)
    per={t:eval_symbol(x["candles"]) for t,x in payload.get("symbols",{}).items()}
    valid={t:v for t,v in per.items() if v.get("status")=="OK"}
    summary={}
    for variant in VARIANTS:
      summary[variant]={}
      for c in COSTS:
        ts=[tr for v in valid.values() for tr in v["trades"][variant]]
        s=stats(ts,c);by=[stats(v["trades"][variant],c) for v in valid.values() if v["trades"][variant]]
        s["tickers_with_trades"]=len(by);s["tickers_positive"]=sum(z["total_compounded_return_pct"]>0 for z in by)
        s["median_ticker_compounded_return_pct"]=statistics.median(z["total_compounded_return_pct"] for z in by) if by else None
        summary[variant][str(c)]=s
    report={"created_utc":datetime.now(timezone.utc).isoformat(),"data_source":"Finam technical H1 archived dataset",
      "design":"Chronological development folds entirely inside first 80% per ticker. Final 20% excluded. No parameter tuning on final segment.",
      "variants":"20-bar breakout + SMA50 direction/slope filter; exits after 12/24/36 bars or cross of SMA50 (max 36 bars).",
      "costs_bps_each_side":COSTS,"summary":summary,"symbols":per,
      "limitations":["archive overlaps prior research; development folds are not independent fresh data","fees/spread/slippage/borrow/taxes not modeled; costs are illustrative","H1 bars; horizons measured in trading bars","research only; no signals or orders"]}
    out=ROOT/"reports";out.mkdir(exist_ok=True,parents=True)
    path=out/f"sma50-exit-robustness-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":"OK","tickers":len(valid),"summary":summary,"report":str(path)},ensure_ascii=False))
if __name__=="__main__":main()
