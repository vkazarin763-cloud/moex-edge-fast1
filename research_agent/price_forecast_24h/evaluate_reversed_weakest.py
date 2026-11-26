"""Test reversing the weakest predeclared entry rule without changing timing."""
import gzip,json
from datetime import datetime,timezone
from pathlib import Path
from research_agent.price_forecast_24h.evaluate_direction_mechanics import (
 ROOT,MIN_BARS,HOLDOUT_FRAC,indicators,make_signals,run_window,summarize
)
from research_agent.price_forecast_24h.evaluate_ohlc_strategies import clean_bars

RULE="long_ema20_pullback"
def invert(signals): return [-x for x in signals]
def main():
 data=ROOT/"data"/"H1_HISTORY.json.gz"
 with gzip.open(data,"rt",encoding="utf-8") as f: payload=json.load(f)
 pooled={"original":{"development":[],"holdout":[],"folds":{1:[],2:[],3:[]}},
         "reversed":{"development":[],"holdout":[],"folds":{1:[],2:[],3:[]}}}
 symbols={}
 for ticker,obj in payload.get("symbols",{}).items():
  bars,q=clean_bars(obj["candles"])
  if len(bars)<MIN_BARS:
   symbols[ticker]={"status":"INSUFFICIENT","bars":len(bars),**q};continue
  ema,sma,_=indicators(bars); sig=make_signals(bars,ema,sma)[RULE]
  inv=invert(sig)
  cutoff=int(len(bars)*(1-HOLDOUT_FRAC)); ds=int(cutoff*.50);w=(cutoff-ds)//3
  folds=[(ds+k*w,cutoff if k==2 else ds+(k+1)*w) for k in range(3)]
  result={}
  for name,series in (("original",sig),("reversed",inv)):
   dev=[]; fs={}
   for no,(a,b) in enumerate(folds,1):
    ts=run_window(bars,series,a,b);dev.extend(ts);pooled[name]["folds"][no].extend(ts);fs[str(no)]=summarize(ts)
   ho=run_window(bars,series,cutoff,len(bars))
   pooled[name]["development"].extend(dev);pooled[name]["holdout"].extend(ho)
   result[name]={"development":summarize(dev),"folds":fs,"holdout":summarize(ho)}
  symbols[ticker]={"status":"OK","bars":len(bars),"holdout_start":bars[cutoff]["timestamp"],"holdout_end":bars[-1]["timestamp"],"variants":result,**q}
 agg={}
 for name in pooled:
  agg[name]={"development":summarize(pooled[name]["development"]),
   "holdout":summarize(pooled[name]["holdout"]),
   "development_folds":{str(k):summarize(v) for k,v in pooled[name]["folds"].items()}}
 report={"created_utc":datetime.now(timezone.utc).isoformat(),"source":"Finam technical H1 archive",
  "rule":RULE,"protocol":"Use exactly the original EMA20 pullback signal timestamps and next-bar-open entries / 12-bar exits. Reversed version changes only direction from LONG to SHORT. Same trade opportunities, no reselection. First 80% development split into three chronological folds; final 20% holdout. Costs 5/10 bps each side.",
  "aggregate":agg,"symbols_evaluated":sum(v.get("status")=="OK" for v in symbols.values()),"symbols":symbols,
  "limitations":["Same dataset and signal timestamps as earlier research; not independent validation.",
  "Shorting availability, borrow costs, real spreads, commissions, slippage and taxes not modeled.",
  "5/10 bps per side are illustrative; aggregate compounded sequence is not portfolio return.",
  "Research only; no production changes or orders."]}
 out=ROOT/"reports";out.mkdir(parents=True,exist_ok=True)
 path=out/f"reversed-weakest-strategy-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
 path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\\n")
 print(json.dumps({"status":"OK","report":str(path),"aggregate":agg},ensure_ascii=False))
if __name__=="__main__":main()
