"""Research-only OHLC strategy backtest with next-bar entries and explicit cost scenarios."""
from __future__ import annotations
import csv,gzip,json,math,statistics
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path("research_agent/price_forecast_24h")
DATA,REPORTS=ROOT/"data",ROOT/"reports"
HORIZON=24
FOLDS=4
COST_BPS_PER_SIDE=(0,5,10)
BREAKOUT_LOOKBACK=20
MEAN_LOOKBACK=20
MEAN_BAND_MULTIPLE=2.0


def clean_bars(rows):
    out=[];seen=set()
    quality={"duplicates":0,"invalid_ohlc":0,"weekend_bars_excluded":0}
    for r in sorted(rows,key=lambda x:x["timestamp"]):
        ts=datetime.fromisoformat(r["timestamp"])
        key=ts.isoformat()
        if key in seen:
            quality["duplicates"]+=1;continue
        seen.add(key)
        o,h,l,c=(float(r[k]) for k in ("open","high","low","close"))
        if (not all(math.isfinite(x) and x>0 for x in (o,h,l,c))
            or l>min(o,c) or h<max(o,c) or l>h):
            quality["invalid_ohlc"]+=1;continue
        if ts.weekday()>=5:
            quality["weekend_bars_excluded"]+=1;continue
        out.append({"timestamp":ts.isoformat(),"open":o,"high":h,"low":l,"close":c})
    return out,quality


def split_folds(n):
    first=int(n*.50)
    width=(n-first)//FOLDS
    result=[]
    for k in range(FOLDS):
        start=first+k*width
        end=n if k==FOLDS-1 else first+(k+1)*width
        if end-start>HORIZON+1: result.append((start,end))
    return result


def indicators(bars):
    n=len(bars)
    prior_high=[None]*n;prior_low=[None]*n
    mean=[None]*n;sd=[None]*n
    for i in range(n):
        if i>=BREAKOUT_LOOKBACK:
            window=bars[i-BREAKOUT_LOOKBACK:i]
            prior_high[i]=max(x["high"] for x in window)
            prior_low[i]=min(x["low"] for x in window)
        if i>=MEAN_LOOKBACK-1:
            values=[x["close"] for x in bars[i-MEAN_LOOKBACK+1:i+1]]
            mean[i]=statistics.fmean(values)
            sd[i]=statistics.pstdev(values)
    return prior_high,prior_low,mean,sd


def make_trade(bars,signal_i,fold_end,direction,exit_mode,mean):
    entry_i=signal_i+1
    if entry_i>=fold_end:return None
    entry=bars[entry_i]["open"]
    max_exit=min(fold_end-1,entry_i+HORIZON-1)
    exit_i=max_exit
    for j in range(entry_i,max_exit+1):
        if exit_mode=="mean" and mean[j] is not None:
            if (direction==1 and bars[j]["close"]>=mean[j]) or (direction==-1 and bars[j]["close"]<=mean[j]):
                exit_i=j
                break
    exit_price=bars[exit_i]["close"]
    gross=direction*math.log(exit_price/entry)
    return {"entry_time":bars[entry_i]["timestamp"],"exit_time":bars[exit_i]["timestamp"],
            "direction":"LONG" if direction==1 else "SHORT",
            "entry_price":entry,"exit_price":exit_price,"gross_return":gross,
            "holding_bars":exit_i-entry_i+1}


def simulate(bars,start,end):
    ph,pl,mean,sd=indicators(bars)
    strategies={"breakout_20":[],"mean_reversion_20_2sd":[]}
    i=start
    while i<end-1:
        direction=0
        if ph[i] is not None:
            if bars[i]["close"]>ph[i]:direction=1
            elif bars[i]["close"]<pl[i]:direction=-1
        if direction:
            trade=make_trade(bars,i,end,direction,"fixed",mean)
            if trade:strategies["breakout_20"].append(trade)
            i+=HORIZON
            continue
        if mean[i] is not None and sd[i] is not None and sd[i]>0:
            upper=mean[i]+MEAN_BAND_MULTIPLE*sd[i]
            lower=mean[i]-MEAN_BAND_MULTIPLE*sd[i]
            if bars[i]["close"]<lower:direction=1
            elif bars[i]["close"]>upper:direction=-1
        if direction:
            trade=make_trade(bars,i,end,direction,"mean",mean)
            if trade:strategies["mean_reversion_20_2sd"].append(trade)
            i+=HORIZON
        else:
            i+=1
    return strategies


def stats(trades,cost_bps):
    if not trades:
        return {"trades":0,"win_rate_pct":None,"mean_net_return_pct":None,
                "median_net_return_pct":None,"total_compounded_return_pct":None,
                "profit_factor":None,"max_drawdown_pct":None,"mean_holding_bars":None}
    cost=2*cost_bps/10000
    net=[t["gross_return"]-cost for t in trades]
    wins=[x for x in net if x>0];losses=[x for x in net if x<0]
    equity=peak=1.0;max_dd=0.0
    for x in net:
        equity*=math.exp(x);peak=max(peak,equity)
        max_dd=max(max_dd,(peak-equity)/peak)
    gross_profit=sum(wins);gross_loss=abs(sum(losses))
    return {"trades":len(net),"win_rate_pct":sum(x>0 for x in net)/len(net)*100,
        "mean_net_return_pct":statistics.fmean(net)*100,
        "median_net_return_pct":statistics.median(net)*100,
        "total_compounded_return_pct":(math.exp(sum(net))-1)*100,
        "profit_factor":gross_profit/gross_loss if gross_loss else (None if not wins else "inf"),
        "max_drawdown_pct":max_dd*100,
        "mean_holding_bars":statistics.fmean(t["holding_bars"] for t in trades)}


def evaluate_symbol(rows):
    bars,q=clean_bars(rows)
    folds=split_folds(len(bars))
    if len(folds)<3:
        return {"status":"INSUFFICIENT_DATA","bars_after_filter":len(bars),"folds":len(folds),**q}
    combined={name:[] for name in ("breakout_20","mean_reversion_20_2sd")}
    fold_info=[]
    for no,(start,end) in enumerate(folds,1):
        trades=simulate(bars,start,end)
        fold_info.append({"fold":no,"test_start":bars[start]["timestamp"],
            "test_end":bars[end-1]["timestamp"],"test_bars":end-start,
            "breakout_trades":len(trades["breakout_20"]),
            "mean_reversion_trades":len(trades["mean_reversion_20_2sd"])})
        for name in combined:combined[name].extend(trades[name])
    return {"status":"OK","bars_after_filter":len(bars),"folds":fold_info,
        "strategies":{name:{str(cost):stats(trades,cost) for cost in COST_BPS_PER_SIDE}
                      for name,trades in combined.items()},
        "trades":combined,**q}


def aggregate(results):
    out={}
    for name in ("breakout_20","mean_reversion_20_2sd"):
        out[name]={}
        for cost in COST_BPS_PER_SIDE:
            all_trades=[t for v in results.values() if v.get("status")=="OK"
                        for t in v["trades"][name]]
            s=stats(all_trades,cost)
            by_ticker=[stats(v["trades"][name],cost) for v in results.values()
                       if v.get("status")=="OK" and v["trades"][name]]
            s["tickers_with_trades"]=len(by_ticker)
            s["tickers_with_positive_total_return"]=sum(x["total_compounded_return_pct"]>0 for x in by_ticker)
            s["median_ticker_total_return_pct"]=statistics.median(
                x["total_compounded_return_pct"] for x in by_ticker) if by_ticker else None
            out[name][str(cost)] = s
    return out


def main():
    path=DATA/"H1_HISTORY.json.gz"
    if not path.exists():raise SystemExit("Cumulative H1_HISTORY.json.gz not found")
    with gzip.open(path,"rt",encoding="utf-8") as f:payload=json.load(f)
    REPORTS.mkdir(parents=True,exist_ok=True)
    results={t:evaluate_symbol(v["candles"]) for t,v in payload.get("symbols",{}).items()}
    valid={t:v for t,v in results.items() if v.get("status")=="OK"}
    summary=aggregate(valid)
    report={"generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "source":"Finam technical H1","universe_size":len(results),"symbols_evaluated":len(valid),
        "validation":"four sequential non-overlapping test blocks in final 50% of each symbol history; indicators use only current and prior completed bars; each strategy is reset at fold boundaries",
        "execution":"signal on completed close; entry at next H1 open; exit at close on mean-line cross or after at most 24 bars; no overlapping positions per strategy and ticker",
        "strategies":{"breakout_20":"LONG above prior 20-bar high; SHORT below prior 20-bar low; fixed 24-bar maximum holding period",
            "mean_reversion_20_2sd":"LONG below 20-close SMA minus 2 population standard deviations; SHORT above SMA plus 2 standard deviations; exit on SMA cross or after at most 24 bars"},
        "cost_scenarios":"0, 5, and 10 basis points per side (round trip 0, 10, 20 bps); illustrative assumptions, not verified Finam tariffs or actual spreads",
        "limitations":["gross and assumed-cost simulations only; no real order-book spread, queue, fills, borrow availability, taxes or market impact",
            "short-selling availability and instrument constraints are not validated",
            "H1 bars are Finam technical data; 24 bars do not equal 24 clock hours",
            "fixed 44-symbol universe may have survivorship bias",
            "no capital allocation or cross-symbol portfolio simulation",
            "research only; no signals, Telegram, broker orders or production changes"],
        "data_quality_totals":{k:sum(v.get(k,0) for v in results.values())
            for k in ("weekend_bars_excluded","duplicates","invalid_ohlc")},
        "summary_by_strategy":summary,"results":results}
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    jp=REPORTS/f"ohlc-strategy-test-{stamp}.json"
    jp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    cp=REPORTS/f"ohlc-strategy-test-{stamp}.csv"
    fields=["ticker","strategy","cost_bps_per_side","trades","win_rate_pct",
        "mean_net_return_pct","median_net_return_pct","total_compounded_return_pct",
        "profit_factor","max_drawdown_pct","mean_holding_bars"]
    with cp.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for ticker,v in results.items():
            if v.get("status")!="OK":continue
            for name,levels in v["strategies"].items():
                for cost,s in levels.items():w.writerow({"ticker":ticker,"strategy":name,
                    "cost_bps_per_side":cost,**s})
    print(json.dumps({"status":"OK","symbols":len(results),"evaluated":len(valid),
        "summary_by_strategy":summary,"json_report":str(jp),"csv_report":str(cp)},ensure_ascii=False))


if __name__=="__main__":main()
