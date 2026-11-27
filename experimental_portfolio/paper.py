"""Forward-only paper ledger. Historical backtests never seed live paper holdings."""
from __future__ import annotations
from datetime import datetime,timezone
from typing import Any
from experimental_portfolio.engine import (
    CASH_KEY,ESTIMATED_ONE_WAY_COST,MIN_COMMON_BARS,TREND_WINDOW,
    UNIVERSE,_target_weights,
)

def update_paper_ledger(history:dict[str,list[dict[str,Any]]],
                        existing:dict[str,Any]|None=None,
                        generated_at:datetime|None=None)->dict[str,Any]:
    """Mark existing paper holdings to market and rebalance only on newly seen sessions."""
    generated_at=generated_at or datetime.now(timezone.utc)
    eligible={s:r for s,r in history.items() if len(r)>=MIN_COMMON_BARS}
    common=set.intersection(*(set(x["date"] for x in rows) for rows in eligible.values())) if eligible else set()
    dates=sorted(common)
    if len(eligible)<6 or len(dates)<MIN_COMMON_BARS:
        return {**(existing or {}),"status":"DATA_INSUFFICIENT","updated_at_utc":generated_at.isoformat(),
                "paper_only":True,"orders_placed":False}
    rows_by_symbol={s:{r["date"]:r for r in rows} for s,rows in eligible.items()}
    prices={s:[rows_by_symbol[s][day].get("adjusted_close",rows_by_symbol[s][day]["close"]) for day in dates]
            for s in eligible}
    opens={}
    for s in eligible:
        vals=[]
        for day in dates:
            row=rows_by_symbol[s][day]
            raw_close=row.get("raw_close",row["close"])
            adjusted_close=row.get("adjusted_close",row["close"])
            factor=adjusted_close/raw_close if raw_close else 1.0
            vals.append(row["open"]*factor)
        opens[s]=vals

    if existing is None:
        return {
            "version":1,"status":"INITIALIZED_WAITING_FOR_NEXT_SESSION",
            "start_date":dates[-1],"last_processed_date":dates[-1],
            "updated_at_utc":generated_at.isoformat(),"nav_index":100.0,
            "high_watermark":100.0,"max_drawdown":0.0,"last_daily_return":0.0,
            "holdings":[],"cash_weight":1.0,"last_rebalance_month":None,
            "rebalance_count":0,"cumulative_turnover":0.0,
            "paper_only":True,"orders_placed":False,
            "note":"Initialized after the latest completed close. First virtual entry will use the next available session open.",
        }

    ledger=dict(existing)
    last_day=ledger.get("last_processed_date")
    try: last_index=dates.index(last_day)
    except ValueError:
        ledger.update({"status":"LEDGER_DATE_NOT_IN_CURRENT_HISTORY","updated_at_utc":generated_at.isoformat(),
                       "paper_only":True,"orders_placed":False})
        return ledger
    if last_index>=len(dates)-1:
        ledger.update({"status":"WAITING_FOR_NEW_SESSION","updated_at_utc":generated_at.isoformat(),
                       "paper_only":True,"orders_placed":False})
        return ledger

    weights={item["symbol"]:float(item["weight"]) for item in ledger.get("holdings",[])}
    weights[CASH_KEY]=float(ledger.get("cash_weight",max(0.0,1.0-sum(weights.values()))))
    nav=float(ledger.get("nav_index",100.0))
    high=max(float(ledger.get("high_watermark",nav)),nav)
    max_dd=float(ledger.get("max_drawdown",0.0))
    last_rebalance_month=ledger.get("last_rebalance_month")
    rebalance_count=int(ledger.get("rebalance_count",0))
    turnover_total=float(ledger.get("cumulative_turnover",0.0))
    processed=0
    for i in range(last_index+1,len(dates)):
        day=dates[i]
        before=nav
        # Overnight gap belongs to the holdings carried from the previous close.
        overnight=sum(w*(opens[s][i]/prices[s][i-1]-1.0)
                      for s,w in weights.items() if s!=CASH_KEY)
        nav*=1.0+overnight

        if last_rebalance_month is None or day[:7]!=last_rebalance_month:
            target_assets=_target_weights(prices,sorted(prices),i-1)
            target=dict(target_assets)
            target[CASH_KEY]=max(0.0,1.0-sum(target_assets.values()))
            turnover=sum(abs(target.get(s,0.0)-weights.get(s,0.0))
                         for s in set(target)|set(weights))/2.0
            nav*=max(0.0,1.0-turnover*ESTIMATED_ONE_WAY_COST)
            turnover_total+=turnover
            rebalance_count+=1
            weights=target
            last_rebalance_month=day[:7]

        # Intraday return is measured from the adjusted open to adjusted close.
        intraday=sum(w*(prices[s][i]/opens[s][i]-1.0)
                     for s,w in weights.items() if s!=CASH_KEY)
        nav*=1.0+intraday
        daily_return=nav/before-1.0 if before else 0.0
        high=max(high,nav)
        max_dd=min(max_dd,nav/high-1.0)
        ledger["last_processed_date"]=day
        ledger["last_daily_return"]=round(daily_return,8)
        processed+=1

    last_date=dates[-1]
    holdings=[]
    for symbol,weight in sorted(weights.items()):
        if symbol==CASH_KEY or weight<=0: continue
        row=rows_by_symbol[symbol][last_date]
        holdings.append({
            "symbol":symbol,"weight":round(weight,6),
            "latest_close":row.get("raw_close",row["close"]),
            "adjusted_close":prices[symbol][-1],
            "asset_class":next((x["asset_class"] for x in UNIVERSE if x["symbol"]==symbol),"unknown"),
        })
    ledger.update({
        "status":"UPDATED" if processed else "WAITING_FOR_NEW_SESSION",
        "updated_at_utc":generated_at.isoformat(),"last_processed_date":last_date,
        "nav_index":round(nav,8),"high_watermark":round(high,8),
        "max_drawdown":round(max_dd,8),"holdings":holdings,
        "cash_weight":round(max(0.0,1.0-sum(x["weight"] for x in holdings)),6),
        "last_rebalance_month":last_rebalance_month,
        "rebalance_count":rebalance_count,"cumulative_turnover":round(turnover_total,8),
        "sessions_processed":int(ledger.get("sessions_processed",0))+processed,
        "paper_only":True,"orders_placed":False,
    })
    return ledger
