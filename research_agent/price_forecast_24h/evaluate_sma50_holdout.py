"""Frozen SMA50-filtered breakout on final chronological holdout; research only."""
from __future__ import annotations
import gzip,json,statistics,math
from datetime import datetime,timezone
from pathlib import Path
from research_agent.price_forecast_24h.evaluate_ohlc_strategies import clean_bars,indicators,make_trade,stats,HORIZON

ROOT=Path("research_agent/price_forecast_24h")
COSTS=(5,10)
HOLDOUT_FRAC=0.20

def test_symbol(rows):
    bars,q=clean_bars(rows)
    if len(bars)<300:return {"status":"INSUFFICIENT_DATA","bars":len(bars),**q}
    start=int(len(bars)*(1-HOLDOUT_FRAC)); end=len(bars)
    ph,pl,mean,sd,sma50,rsi=indicators(bars)
    trades=[];i=start
    while i<end-1:
        direction=1 if ph[i] is not None and bars[i]["close"]>ph[i] else (-1 if pl[i] is not None and bars[i]["close"]<pl[i] else 0)
        filtered=0
        if direction and sma50[i] is not None and i>=51:
            prev=statistics.fmean(x["close"] for x in bars[i-50:i])
            if direction==1 and bars[i]["close"]>sma50[i] and sma50[i]>prev:filtered=1
            elif direction==-1 and bars[i]["close"]<sma50[i] and sma50[i]<prev:filtered=-1
        if filtered:
            t=make_trade(bars,i,end,filtered,"fixed",mean)
            if t:trades.append(t)
            i+=HORIZON
        else:i+=1
    return {"status":"OK","bars":len(bars),"holdout_start":bars[start]["timestamp"],
        "holdout_end":bars[end-1]["timestamp"],"holdout_bars":end-start,
        "trades":trades,"stats":{str(c):stats(trades,c) for c in COSTS},**q}

def main():
    with gzip.open(ROOT/"data"/"H1_HISTORY.json.gz","rt",encoding="utf-8") as f:payload=json.load(f)
    results={ticker:test_symbol(v["candles"]) for ticker,v in payload.get("symbols",{}).items()}
    valid={k:v for k,v in results.items() if v.get("status")=="OK"}
    alltrades=[t for v in valid.values() for t in v["trades"]]
    summary={}
    for c in COSTS:
        s=stats(alltrades,c)
        active=[stats(v["trades"],c) for v in valid.values() if v["trades"]]
        s["active_tickers"]=len(active)
        s["positive_tickers"]=sum(x["total_compounded_return_pct"]>0 for x in active)
        s["median_ticker_compounded_return_pct"]=statistics.median(x["total_compounded_return_pct"] for x in active) if active else None
        summary[str(c)]=s
    report={"generated_at_utc":datetime.now(timezone.utc).isoformat(),
      "data_source":"Finam technical H1; existing archived dataset",
      "test":"Final chronological 20% per symbol, untouched by this evaluation; prior 80% used only for indicator warmup/history. This is not fresh future data and may overlap earlier strategy research.",
      "strategy_frozen":"20-bar breakout; LONG only above SMA50 with SMA50 rising vs previous bar; SHORT only below SMA50 with SMA50 falling; next H1 open entry; max 24 H1 bars; no overlapping ticker trades.",
      "costs":"5 and 10 bps per side illustrative, not verified fees/spread",
      "summary":summary,"symbols":results,
      "limitations":["same archive as previous research; holdout is chronologically reserved for this run but not truly independent fresh data","no actual spread, order-book fills, slippage, borrow, taxes or market impact","H1 technical candles, 24 bars not necessarily 24 clock hours","no portfolio allocation; aggregated trade sequence is diagnostic only","research-only, no production signals or orders"]}
    out=ROOT/"reports";out.mkdir(parents=True,exist_ok=True)
    path=out/f"sma50-breakout-holdout-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
    print(json.dumps({"status":"OK","symbols":len(results),"tested":len(valid),"summary":summary,"report":str(path)},ensure_ascii=False))
if __name__=="__main__":main()
