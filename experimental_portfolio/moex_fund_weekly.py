"""Weekly momentum/trend research for account-permitted MOEX exchange-traded funds."""
from __future__ import annotations
from datetime import date
import math
from typing import Any

MIN_HISTORY=200
TREND_WEEKS=40
MOMENTUM_WEEKS=13
MAX_HOLDINGS=4
COST=0.001

def _metrics(returns:list[float], dates:list[str])->dict[str,Any]:
    if not returns:return {"observations":0,"total_return":None,"cagr":None,"max_drawdown":None,"volatility":None,"sharpe":None}
    nav=100.; peak=100.; dd=0.
    for r in returns:
        nav*=1+r;peak=max(peak,nav);dd=min(dd,nav/peak-1)
    years=max((date.fromisoformat(dates[-1])-date.fromisoformat(dates[0])).days/365.25,1/365.25)
    avg=sum(returns)/len(returns);var=sum((r-avg)**2 for r in returns)/max(len(returns)-1,1)
    vol=math.sqrt(var)*math.sqrt(52)
    return {"observations":len(returns),"total_return":round(nav/100-1,6),"cagr":round((nav/100)**(1/years)-1,6) if nav>0 else -1,
        "max_drawdown":round(dd,6),"volatility":round(vol,6),"sharpe":round(avg/math.sqrt(var)*math.sqrt(52),4) if var>0 else None,"ending_nav":round(nav,4)}

def run_weekly_backtest(history:dict[str,list[dict]], min_history:int=MIN_HISTORY)->dict[str,Any]:
    eligible={s:rows for s,rows in history.items() if len(rows)>=min_history}
    if len(eligible)<4:return {"status":"INSUFFICIENT_HISTORY","eligible_symbols":sorted(eligible),"excluded_short_history":sorted(set(history)-set(eligible)),"metrics":None}
    dates=sorted(set.intersection(*(set(r["date"] for r in rows) for rows in eligible.values())))
    if len(dates)<TREND_WEEKS+MOMENTUM_WEEKS+10:return {"status":"INSUFFICIENT_COMMON_HISTORY","eligible_symbols":sorted(eligible),"common_bars":len(dates),"metrics":None}
    prices={s:[next(r["close"] for r in rows if r["date"]==d) for d in dates] for s,rows in eligible.items()}
    weights:dict[str,float]={};returns=[];return_dates=[];nav=100.;peak=100.;maxdd=0.;turnover=0.;rebals=0;last_targets={}
    for i in range(TREND_WEEKS,len(dates)):
        d=dates[i]; prev=dates[i-1]
        if i==TREND_WEEKS or d[:7]!=prev[:7]:
            rank=[]
            for s,p in prices.items():
                if i-1<MOMENTUM_WEEKS:continue
                mom=p[i-1]/p[i-1-MOMENTUM_WEEKS]-1
                sma=sum(p[i-TREND_WEEKS:i])/TREND_WEEKS
                if p[i-1]>sma and mom>0:rank.append((mom,s))
            rank.sort(reverse=True);selected=[s for _,s in rank[:MAX_HOLDINGS]]
            neww={s:1/len(selected) for s in selected} if selected else {}
            tr=sum(abs(neww.get(s,0)-weights.get(s,0)) for s in set(neww)|set(weights))/2
            nav*=max(0,1-tr*COST);turnover+=tr;rebals+=1;weights=neww;last_targets=neww
        r=sum(w*(prices[s][i]/prices[s][i-1]-1) for s,w in weights.items())
        nav*=1+r;returns.append(r);return_dates.append(d);peak=max(peak,nav);maxdd=min(maxdd,nav/peak-1)
    m=_metrics(returns,return_dates);m["max_drawdown"]=round(maxdd,6)
    benchmark=None
    for candidate in ("TMOS@MISX","TMOS","SBMX@MISX","SBMX"):
        if candidate in prices:
            br=[prices[candidate][i]/prices[candidate][i-1]-1 for i in range(TREND_WEEKS,len(dates))]
            benchmark=_metrics(br,return_dates);benchmark["symbol"]=candidate;break
    return {"status":"READY","period":{"start":return_dates[0],"end":return_dates[-1]},"common_bars":len(dates),
      "eligible_symbols":sorted(eligible),"excluded_short_history":sorted(set(history)-set(eligible)),
      "strategy":{"trend_filter":"weekly close above 40-week SMA","momentum":"13-week positive momentum","selection":"top 4 equal-weight, monthly rebalance","cost_one_way":COST},
      "metrics":m,"benchmark_buy_hold":benchmark,"last_targets":[{"symbol":s,"weight":round(w,6)} for s,w in sorted(last_targets.items())],
      "turnover_total":round(turnover,4),"rebalances":rebals,"notice":"Historical weekly simulation only; not evidence of future profitability."}

def current_weekly_targets(history:dict[str,list[dict]], min_history:int=MIN_HISTORY)->list[dict[str,float|str]]:
    eligible={s:r for s,r in history.items() if len(r)>=min_history}
    if len(eligible)<4:return []
    dates=sorted(set.intersection(*(set(r["date"] for r in rows) for rows in eligible.values()))
    if len(dates)<TREND_WEEKS:return []
    idx=len(dates)-1
    ranked=[]
    for s,rows in eligible.items():
        p=[next(r["close"] for r in rows if r["date"]==d) for d in dates]
        mom=p[idx]/p[idx-MOMENTUM_WEEKS]-1
        sma=sum(p[idx-TREND_WEEKS+1:idx+1])/TREND_WEEKS
        if p[idx]>sma and mom>0:ranked.append((mom,s))
    ranked.sort(reverse=True)
    chosen=[s for _,s in ranked[:MAX_HOLDINGS]]
    return [{"symbol":s,"weight":round(1/len(chosen),6)} for s in chosen] if chosen else []
