"""Research-only ATR risk-control tests for 20-bar breakout + SMA50 trend signals.

Uses chronological development folds inside the first 80% of each ticker's history.
Entry is next-bar open; ATR is known at signal time. Intrabar stop/target collisions
are resolved pessimistically (stop first). No production integration.
"""
from __future__ import annotations
import gzip, json, math, statistics
from datetime import datetime, timezone
from pathlib import Path
from research_agent.price_forecast_24h.evaluate_ohlc_strategies import clean_bars, stats

ROOT=Path("research_agent/price_forecast_24h")
COSTS=(5,10)
HOLDOUT_FRAC=.20
FOLDS=3
ATR_PERIOD=14
MAX_HOLD=12
# (stop distance in ATR, reward/risk target); None target means stop-only/time exit.
RISK_VARIANTS={"time_12":(None,None),"stop_1.5atr":(1.5,None),
 "stop_2atr":(2.0,None),"stop_2.5atr":(2.5,None),
 "bracket_1.5atr_2r":(1.5,2.0),"bracket_2atr_2r":(2.0,2.0)}

def calc_atr(bars):
    tr=[None]*len(bars)
    for i in range(1,len(bars)):
        p=bars[i-1]["close"]; b=bars[i]
        tr[i]=max(b["high"]-b["low"],abs(b["high"]-p),abs(b["low"]-p))
    atr=[None]*len(bars)
    for i in range(ATR_PERIOD,len(bars)):
        vals=[tr[j] for j in range(i-ATR_PERIOD+1,i+1)]
        if all(x is not None for x in vals): atr[i]=statistics.fmean(vals)
    return atr

def make_signals(bars):
    n=len(bars); ph=[None]*n; pl=[None]*n; sma=[None]*n
    for i in range(n):
        if i>=20:
            ph[i]=max(x["high"] for x in bars[i-20:i])
            pl[i]=min(x["low"] for x in bars[i-20:i])
        if i>=50: sma[i]=statistics.fmean(x["close"] for x in bars[i-49:i+1])
    out=[0]*n
    for i in range(51,n):
        d=1 if ph[i] is not None and bars[i]["close"]>ph[i] else (-1 if pl[i] is not None and bars[i]["close"]<pl[i] else 0)
        if d==1 and bars[i]["close"]>sma[i] and sma[i]>statistics.fmean(x["close"] for x in bars[i-50:i]): out[i]=1
        elif d==-1 and bars[i]["close"]<sma[i] and sma[i]<statistics.fmean(x["close"] for x in bars[i-50:i]): out[i]=-1
    return out

def trade_one(bars, signal_i, fold_end, direction, atr, variant):
    entry_i=signal_i+1
    if entry_i>=fold_end or atr[signal_i] is None or atr[signal_i]<=0: return None
    entry=bars[entry_i]["open"]; stop_mult,target_r=RISK_VARIANTS[variant]
    risk=(stop_mult*atr[signal_i]) if stop_mult else None
    stop=(entry-direction*risk) if risk else None
    target=(entry+direction*risk*target_r) if risk and target_r else None
    last=min(fold_end-1,entry_i+MAX_HOLD-1); exit_i=last; exit_price=bars[last]["close"]; reason="time"
    for j in range(entry_i,last+1):
        b=bars[j]
        # Gap-aware and pessimistic: if stop and target both touched, stop wins.
        if stop is not None:
            stop_hit=(b["low"]<=stop) if direction==1 else (b["high"]>=stop)
            if stop_hit:
                exit_i=j
                exit_price=min(stop,b["open"]) if direction==1 else max(stop,b["open"])
                reason="stop"; break
        if target is not None:
            target_hit=(b["high"]>=target) if direction==1 else (b["low"]<=target)
            if target_hit:
                exit_i=j; exit_price=max(target,b["open"]) if direction==1 else min(target,b["open"])
                reason="target"; break
    gross=direction*math.log(exit_price/entry)
    return {"entry_time":bars[entry_i]["timestamp"],"exit_time":bars[exit_i]["timestamp"],
      "direction":"LONG" if direction==1 else "SHORT","entry_price":entry,"exit_price":exit_price,
      "gross_return":gross,"holding_bars":exit_i-entry_i+1,"exit_index":exit_i,"exit_reason":reason,"variant":variant}

def evaluate_symbol(rows):
    bars,q=clean_bars(rows)
    if len(bars)<400: return {"status":"INSUFFICIENT","bars":len(bars),**q}
    atr=calc_atr(bars); signals=make_signals(bars)
    cutoff=int(len(bars)*(1-HOLDOUT_FRAC)); first=int(cutoff*.50); width=(cutoff-first)//FOLDS
    folds=[(first+k*width,cutoff if k==FOLDS-1 else first+(k+1)*width) for k in range(FOLDS)]
    results={v:[] for v in RISK_VARIANTS}
    foldmeta=[]
    for fi,(a,b) in enumerate(folds,1):
        foldmeta.append({"fold":fi,"from":bars[a]["timestamp"],"to":bars[b-1]["timestamp"],"bars":b-a})
        for v in RISK_VARIANTS:
            i=a
            while i<b-1:
                if signals[i]:
                    t=trade_one(bars,i,b,signals[i],atr,v)
                    if t:
                        t["fold"]=fi;results[v].append(t);i=t["exit_index"]+1
                    else:i+=1
                else:i+=1
    return {"status":"OK","bars":len(bars),"development_end":bars[cutoff-1]["timestamp"],
      "folds":foldmeta,"trades":results,**q}

def main():
    with gzip.open(ROOT/"data"/"H1_HISTORY.json.gz","rt",encoding="utf-8") as f: payload=json.load(f)
    per={t:evaluate_symbol(x["candles"]) for t,x in payload.get("symbols",{}).items()}
    valid={t:v for t,v in per.items() if v.get("status")=="OK"}
    summary={}
    for variant in RISK_VARIANTS:
        summary[variant]={}
        for cost in COSTS:
            ts=[t for v in valid.values() for t in v["trades"][variant]]
            by=[stats(v["trades"][variant],cost) for v in valid.values() if v["trades"][variant]]
            s=stats(ts,cost);s["tickers_with_trades"]=len(by)
            s["tickers_positive"]=sum(x["total_compounded_return_pct"]>0 for x in by)
            s["median_ticker_compounded_return_pct"]=statistics.median(x["total_compounded_return_pct"] for x in by) if by else None
            reasons={}
            for t in ts: reasons[t["exit_reason"]]=reasons.get(t["exit_reason"],0)+1
            s["exit_reasons"]=reasons;summary[variant][str(cost)]=s
    report={"created_utc":datetime.now(timezone.utc).isoformat(),"data_source":"Finam technical H1 archive",
      "design":"20-bar breakout with SMA50 direction and rising/falling slope; next-bar open entry; non-overlapping trades; first 80% development data split into 3 chronological folds; final 20% untouched.",
      "risk_variants":RISK_VARIANTS,"atr_period":ATR_PERIOD,"max_holding_bars":MAX_HOLD,
      "intrabar_policy":"stop is checked before target; gaps are filled at worse of stop and open; target gaps filled at better of target and open.",
      "costs_bps_each_side":COSTS,"summary":summary,"symbols":per,
      "limitations":["same archived dataset as earlier experiments; not independent fresh data","ATR exits are simulated from H1 OHLC; intra-candle path unknown","fees, real spread, slippage, borrow and taxes not modeled; costs illustrative","no final-20% holdout use; no deployment or signals"]}
    out=ROOT/"reports";out.mkdir(parents=True,exist_ok=True)
    path=out/f"atr-risk-controls-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":"OK","tickers":len(valid),"summary":summary,"report":str(path)},ensure_ascii=False))
if __name__=="__main__": main()
