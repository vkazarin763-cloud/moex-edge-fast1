"""Research-only comparison of distinct LONG and SHORT H1 entry mechanics.

Predeclared rules, causal indicators, next-bar-open entries, fixed 12-bar exits.
Development folds and final chronological 20% are reported separately. No
parameter search, production integration, signals, or orders.
"""
from __future__ import annotations
import gzip, json, math, statistics
from datetime import datetime, timezone
from pathlib import Path
from research_agent.price_forecast_24h.evaluate_ohlc_strategies import clean_bars, stats

ROOT=Path("research_agent/price_forecast_24h")
COSTS=(5,10)
HOLDOUT_FRAC=.20
MAX_HOLD=12
MIN_BARS=400
VARIANTS=(
    "long_breakout_20", "long_ema20_pullback", "long_momentum_10",
    "short_breakdown_20", "short_ema20_failed_bounce", "short_momentum_10",
)

def indicators(bars):
    n=len(bars); ema20=[None]*n; sma50=[None]*n; atr14=[None]*n
    alpha=2/(20+1)
    for i,b in enumerate(bars):
        ema20[i]=b["close"] if i==0 else alpha*b["close"]+(1-alpha)*ema20[i-1]
        if i>=49: sma50[i]=statistics.fmean(x["close"] for x in bars[i-49:i+1])
        if i>=14:
            trs=[]
            for j in range(i-13,i+1):
                prev=bars[j-1]["close"]
                trs.append(max(bars[j]["high"]-bars[j]["low"],abs(bars[j]["high"]-prev),abs(bars[j]["low"]-prev)))
            atr14[i]=statistics.fmean(trs)
    return ema20,sma50,atr14

def make_signals(bars, ema, sma):
    n=len(bars); out={v:[0]*n for v in VARIANTS}
    for i in range(51,n):
        b=bars[i]; prev=bars[i-1]
        if sma[i] is None: continue
        up=b["close"]>sma[i] and sma[i]>sma[i-1]
        down=b["close"]<sma[i] and sma[i]<sma[i-1]
        prior20=bars[i-20:i]; prior10=bars[i-10:i]
        if up:
            if b["close"]>max(x["high"] for x in prior20): out["long_breakout_20"][i]=1
            # Pullback touches EMA20 and closes back above it while trend remains rising.
            if b["low"]<=ema[i] and b["close"]>ema[i] and prev["close"]>=ema[i-1]:
                out["long_ema20_pullback"][i]=1
            if b["close"]>max(x["high"] for x in prior10): out["long_momentum_10"][i]=1
        if down:
            if b["close"]<min(x["low"] for x in prior20): out["short_breakdown_20"][i]=-1
            # Failed bounce: previous candle reaches EMA20, current closes back below.
            if prev["high"]>=ema[i-1] and b["close"]<ema[i] and b["close"]<b["open"]:
                out["short_ema20_failed_bounce"][i]=-1
            if b["close"]<min(x["low"] for x in prior10): out["short_momentum_10"][i]=-1
    return out

def run_window(bars, signals, start, end):
    trades=[]; i=start
    while i<end-1:
        direction=signals[i]
        if not direction:
            i+=1; continue
        entry_i=i+1
        if entry_i>=end: break
        exit_i=min(end-1,entry_i+MAX_HOLD-1)
        entry=bars[entry_i]["open"]; exitp=bars[exit_i]["close"]
        if entry>0 and exitp>0:
            trades.append({"entry_time":bars[entry_i]["timestamp"],"exit_time":bars[exit_i]["timestamp"],
                "direction":"LONG" if direction==1 else "SHORT","entry_price":entry,"exit_price":exitp,
                "gross_return":direction*math.log(exitp/entry),"holding_bars":exit_i-entry_i+1})
        i=exit_i+1
    return trades

def summarize(trades):
    return {"count":len(trades),
        "5bps":stats(trades,5),"10bps":stats(trades,10),
        "long_count":sum(t["direction"]=="LONG" for t in trades),
        "short_count":sum(t["direction"]=="SHORT" for t in trades)}

def main():
    data=ROOT/"data"/"H1_HISTORY.json.gz"
    if not data.exists(): raise SystemExit("H1_HISTORY.json.gz missing")
    with gzip.open(data,"rt",encoding="utf-8") as f: payload=json.load(f)
    per={}; pooled={v:{"development":[],"holdout":[],"folds":{1:[],2:[],3:[]}} for v in VARIANTS}
    for ticker,obj in payload.get("symbols",{}).items():
        bars,q=clean_bars(obj["candles"])
        if len(bars)<MIN_BARS:
            per[ticker]={"status":"INSUFFICIENT","bars":len(bars),**q}; continue
        ema,sma,atr=indicators(bars); sigs=make_signals(bars,ema,sma)
        cutoff=int(len(bars)*(1-HOLDOUT_FRAC)); dev_start=int(cutoff*.50)
        width=(cutoff-dev_start)//3
        folds=[(dev_start+k*width,cutoff if k==2 else dev_start+(k+1)*width) for k in range(3)]
        tr_result={}
        for v in VARIANTS:
            dev=[]; fold_summaries={}
            for fi,(a,b) in enumerate(folds,1):
                ts=run_window(bars,sigs[v],a,b)
                dev.extend(ts); pooled[v]["folds"][fi].extend(ts)
                fold_summaries[str(fi)]=summarize(ts)
            ho=run_window(bars,sigs[v],cutoff,len(bars))
            pooled[v]["development"].extend(dev); pooled[v]["holdout"].extend(ho)
            tr_result[v]={"development":summarize(dev),"development_folds":fold_summaries,
                          "holdout":summarize(ho)}
        per[ticker]={"status":"OK","bars":len(bars),"development_end":bars[cutoff-1]["timestamp"],
            "holdout_start":bars[cutoff]["timestamp"],"holdout_end":bars[-1]["timestamp"],
            "variants":tr_result,**q}
    aggregate={}
    for v in VARIANTS:
        dev=pooled[v]["development"]; ho=pooled[v]["holdout"]
        by_ticker=[per[t]["variants"][v]["development"] for t in per if per[t].get("status")=="OK"
                   and per[t]["variants"][v]["development"]["count"]]
        hold_by=[per[t]["variants"][v]["holdout"] for t in per if per[t].get("status")=="OK"
                   and per[t]["variants"][v]["holdout"]["count"]]
        aggregate[v]={"development":summarize(dev),"holdout":summarize(ho),
          "development_folds":{str(k):summarize(x) for k,x in pooled[v]["folds"].items()},
          "development_tickers_active":len(by_ticker),
          "development_tickers_positive_5bps":sum(x["5bps"]["total_compounded_return_pct"]>0 for x in by_ticker),
          "holdout_tickers_active":len(hold_by),
          "holdout_tickers_positive_5bps":sum(x["5bps"]["total_compounded_return_pct"]>0 for x in hold_by)}
    report={"created_utc":datetime.now(timezone.utc).isoformat(),"data_source":"Finam technical H1 archive",
      "universe_size":len(payload.get("symbols",{})),"symbols_evaluated":sum(x.get("status")=="OK" for x in per.values()),
      "protocol":"Six predeclared direction-specific rules. Indicators use current and past completed candles only. Signal at close, entry next H1 open, fixed 12-bar close exit, one position per ticker per variant. First 80% split into three chronological development folds; final 20% evaluated separately. No threshold tuning.",
      "rules":{
       "long_breakout_20":"LONG only: close above prior 20-bar high, close above SMA50, SMA50 rising versus prior bar.",
       "long_ema20_pullback":"LONG only: in rising SMA50 regime, candle low touches EMA20 and closes above EMA20; prior close at/above prior EMA20.",
       "long_momentum_10":"LONG only: close above prior 10-bar high in rising SMA50 regime.",
       "short_breakdown_20":"SHORT only: close below prior 20-bar low, close below SMA50, SMA50 falling versus prior bar.",
       "short_ema20_failed_bounce":"SHORT only: in falling SMA50 regime, prior high reaches EMA20 and current candle closes below EMA20 with bearish body.",
       "short_momentum_10":"SHORT only: close below prior 10-bar low in falling SMA50 regime."},
      "costs_bps_each_side":list(COSTS),"max_holding_bars":MAX_HOLD,"aggregate":aggregate,"symbols":per,
      "limitations":["same archived dataset as earlier work; not independent external validation",
       "final 20% results are comparative diagnostics across six predeclared rules, not a fresh untouched sample for repeated selection",
       "actual spread, commissions, slippage, borrow availability/cost and taxes are not modeled; 5/10 bps per side are illustrative",
       "aggregate trade-chain compounding is not a realizable portfolio return",
       "technical Finam H1 data; no production integration, live signals or orders"]}
    out=ROOT/"reports";out.mkdir(parents=True,exist_ok=True)
    path=out/f"direction-specific-entry-mechanics-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":"OK","symbols_evaluated":report["symbols_evaluated"],"aggregate":aggregate,"report":str(path)},ensure_ascii=False))
if __name__=="__main__": main()
