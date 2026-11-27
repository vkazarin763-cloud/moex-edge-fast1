"""Deterministic, read-only global ETF paper-portfolio engine."""
from __future__ import annotations
import csv, io, math, urllib.parse, urllib.request
from datetime import date, datetime, timezone
from typing import Any

SOURCE = "Stooq public daily CSV"
UNIVERSE = [
 {"symbol":"SPY.US","name":"US large-cap equities","asset_class":"equity_us"},
 {"symbol":"QQQ.US","name":"US technology equities","asset_class":"equity_us"},
 {"symbol":"IWM.US","name":"US small-cap equities","asset_class":"equity_us"},
 {"symbol":"EFA.US","name":"Developed markets ex-US","asset_class":"equity_global"},
 {"symbol":"EEM.US","name":"Emerging markets","asset_class":"equity_global"},
 {"symbol":"VGK.US","name":"European equities","asset_class":"equity_europe"},
 {"symbol":"EWJ.US","name":"Japanese equities","asset_class":"equity_asia"},
 {"symbol":"INDA.US","name":"Indian equities","asset_class":"equity_asia"},
 {"symbol":"TLT.US","name":"US long-duration Treasuries","asset_class":"bonds"},
 {"symbol":"IEF.US","name":"US intermediate Treasuries","asset_class":"bonds"},
 {"symbol":"GLD.US","name":"Gold","asset_class":"gold"},
 {"symbol":"DBC.US","name":"Broad commodities","asset_class":"commodities"},
 {"symbol":"VNQ.US","name":"US listed real estate","asset_class":"real_estate"},
 {"symbol":"SHY.US","name":"Short US Treasuries / cash proxy","asset_class":"cash_proxy"},
]
LOOKBACK, TREND_WINDOW, MAX_HOLDINGS = 63, 200, 4
ESTIMATED_ONE_WAY_COST = 0.0010
MIN_COMMON_BARS = 220
CASH_KEY = "__CASH__"

def fetch_daily(symbol: str, start: date, end: date, timeout: int = 25) -> list[dict[str, Any]]:
    params=urllib.parse.urlencode({"s":symbol.lower(),"i":"d","d1":start.strftime("%Y%m%d"),"d2":end.strftime("%Y%m%d")})
    request=urllib.request.Request("https://stooq.com/q/d/l/?"+params,headers={"User-Agent":"experimental-paper-portfolio/1.0"})
    with urllib.request.urlopen(request,timeout=timeout) as response: raw=response.read().decode("utf-8-sig")
    reader=csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or not {"Date","Open","High","Low","Close","Volume"}.issubset(reader.fieldnames):
        raise ValueError("provider returned no OHLCV CSV header")
    rows={}
    for item in reader:
        try:
            day=date.fromisoformat(item["Date"]).isoformat()
            o,h,low,c=(float(item[k]) for k in ("Open","High","Low","Close"))
            vtext=item["Volume"].strip()
            volume=float(vtext) if vtext not in ("","N/A") else None
            if not all(math.isfinite(x) and x>0 for x in (o,h,low,c)): continue
            if h<max(o,low,c) or low>min(o,h,c): continue
            if volume is not None and (not math.isfinite(volume) or volume<0): continue
            rows[day]={"date":day,"open":o,"high":h,"low":low,"close":c,"volume":volume}
        except (KeyError,TypeError,ValueError): continue
    return [rows[k] for k in sorted(rows)]

def _metrics(values:list[float],dates:list[str])->dict[str,Any]:
    if len(values)<2: return {"observations":len(values),"total_return":None,"cagr":None,"max_drawdown":None,"annualized_volatility":None,"sharpe_rf0":None}
    nav=peak=100.0; max_dd=0.0
    for ret in values:
        nav*=1.0+ret; peak=max(peak,nav); max_dd=min(max_dd,nav/peak-1.0)
    years=max((date.fromisoformat(dates[-1])-date.fromisoformat(dates[0])).days/365.25,1/365.25)
    mean=sum(values)/len(values); variance=sum((x-mean)**2 for x in values)/max(1,len(values)-1)
    vol=math.sqrt(variance)*math.sqrt(252); sharpe=mean/math.sqrt(variance)*math.sqrt(252) if variance>0 else None
    return {"observations":len(values),"total_return":round(nav/100.0-1.0,6),
      "cagr":round((nav/100.0)**(1.0/years)-1.0,6) if nav>0 else -1.0,
      "max_drawdown":round(max_dd,6),"annualized_volatility":round(vol,6),
      "sharpe_rf0":round(sharpe,4) if sharpe is not None else None,"ending_nav_index":round(nav,4)}

def _target_weights(prices:dict[str,list[float]],symbols:list[str],index:int)->dict[str,float]:
    ranked=[]
    for symbol in symbols:
        series=prices[symbol]
        if index<TREND_WINDOW-1 or index<LOOKBACK: continue
        momentum=series[index]/series[index-LOOKBACK]-1.0
        sma=sum(series[index-TREND_WINDOW+1:index+1])/TREND_WINDOW
        if series[index]>sma and momentum>0: ranked.append((momentum,symbol))
    ranked.sort(reverse=True)
    chosen=[symbol for _,symbol in ranked[:MAX_HOLDINGS]]
    weight=1.0/len(chosen) if chosen else 0.0
    return {symbol:weight for symbol in chosen}

def build_report(history:dict[str,list[dict[str,Any]]],errors:dict[str,str]|None=None,
                 generated_at:datetime|None=None)->dict[str,Any]:
    errors=errors or {}; generated_at=generated_at or datetime.now(timezone.utc)
    eligible={s:r for s,r in history.items() if len(r)>=MIN_COMMON_BARS}
    common=set.intersection(*(set(x["date"] for x in r) for r in eligible.values())) if eligible else set()
    dates=sorted(common)
    safety={"paper_only":True,"broker_access":False,"orders_placed":False,
            "llm_can_change_weights":False,"real_trading_authorized":False}
    if len(eligible)<6 or len(dates)<MIN_COMMON_BARS:
        return {"status":"INSUFFICIENT_DATA","generated_at_utc":generated_at.isoformat(),"source":SOURCE,
          "eligible_assets":sorted(eligible),"common_daily_bars":len(dates),"data_errors":errors,
          "safety":safety,"message":"Not enough synchronized validated history; no performance is reported."}
    prices={s:[next(x["close"] for x in eligible[s] if x["date"]==day) for day in dates] for s in eligible}
    weights={CASH_KEY:1.0}; nav=100.0; peak=100.0; max_dd=0.0
    daily_returns=[]; return_dates=[]; turnover_total=0.0; rebalances=0; last_targets={}
    for i in range(TREND_WINDOW,len(dates)):
        day,prev=dates[i],dates[i-1]; before=nav
        if i==TREND_WINDOW or day[:7]!=prev[:7]:
            target_assets=_target_weights(prices,sorted(prices),i-1)
            target=dict(target_assets)
            target[CASH_KEY]=max(0.0,1.0-sum(target_assets.values()))
            turnover=sum(abs(target.get(s,0.0)-weights.get(s,0.0)) for s in set(target)|set(weights))/2.0
            nav*=max(0.0,1.0-turnover*ESTIMATED_ONE_WAY_COST)
            turnover_total+=turnover; rebalances+=1; weights=target; last_targets=target_assets
        day_return=sum(w*(prices[s][i]/prices[s][i-1]-1.0) for s,w in weights.items() if s!=CASH_KEY)
        nav*=1.0+day_return
        daily_returns.append(nav/before-1.0 if before else 0.0); return_dates.append(day)
        peak=max(peak,nav); max_dd=min(max_dd,nav/peak-1.0)
    metrics=_metrics(daily_returns,return_dates); metrics["max_drawdown"]=round(max_dd,6)
    benchmark=[prices["SPY.US"][i]/prices["SPY.US"][i-1]-1.0 for i in range(TREND_WINDOW,len(dates))] if "SPY.US" in prices else []
    benchmark_metrics=_metrics(benchmark,return_dates) if benchmark else None
    holdings=[{"symbol":s,"weight":round(w,6),"latest_close":prices[s][-1],
      "asset_class":next((x["asset_class"] for x in UNIVERSE if x["symbol"]==s),"unknown")} for s,w in sorted(last_targets.items())]
    latest_prices={s:{"date":eligible[s][-1]["date"],"close":eligible[s][-1]["close"]} for s in eligible}
    stale=[s for s,x in latest_prices.items() if (generated_at.date()-date.fromisoformat(x["date"])).days>7]
    return {"status":"READY" if not stale else "DATA_STALE","generated_at_utc":generated_at.isoformat(),"source":SOURCE,
      "market_scope":"US-listed global equity, bond, gold, commodity and real-estate ETF proxies",
      "portfolio_model":{"name":"Global 63-session momentum + 200-session trend","initial_nav_index":100.0,
        "currency":"NOT_APPLICABLE_INDEX_UNITS","rebalance":"monthly, using prior completed daily close",
        "selection":"up to four assets with positive 63-session momentum and close above 200-session SMA",
        "weighting":"equal weight; uninvested share remains cash","estimated_one_way_transaction_cost":ESTIMATED_ONE_WAY_COST,
        "cost_assumption_note":"Provisional modeling assumption, not a verified broker tariff or executable spread."},
      "period":{"from":return_dates[0] if return_dates else None,"till":return_dates[-1] if return_dates else None,
        "common_daily_bars":len(dates),"assets_included":sorted(eligible)},
      "performance":metrics,"benchmark_spy_buy_and_hold":benchmark_metrics,"holdings":holdings,
      "cash_weight":round(max(0.0,1.0-sum(x["weight"] for x in holdings)),6),
      "rebalance_count":rebalances,"cumulative_turnover":round(turnover_total,6),
      "latest_prices":latest_prices,"stale_symbols":stale,"data_errors":errors,
      "derivatives":{"status":"RESEARCH_ONLY_NOT_IN_NAV",
        "reason":"Options need historical executable bid/ask, contract, expiry and liquidity data; futures need expiry/roll, multiplier and margin modeling. Existing MOEX scanners remain separate."},
      "safety":safety,"limitations":["Stooq daily closes are not live quotes or executable bid/ask.",
        "Dividend income is not included in this price-return model.",
        "US-listed ETF proxies are not direct ownership of every underlying market.",
        "The 100-point NAV is a normalized research index, not user capital or currency.",
        "Historical results are not a forecast or proof of profitability."]}

def download_universe(start:date,end:date)->tuple[dict[str,list[dict[str,Any]]],dict[str,str]]:
    history,errors={},{}
    for item in UNIVERSE:
        symbol=item["symbol"]
        try:
            rows=fetch_daily(symbol,start,end)
            if len(rows)<MIN_COMMON_BARS: errors[symbol]=f"insufficient_valid_bars:{len(rows)}"
            else: history[symbol]=rows
        except Exception as exc: errors[symbol]=f"{type(exc).__name__}:{str(exc)[:180]}"
    return history,errors
