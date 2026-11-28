"""Read-only global ETF paper-portfolio engine using public daily price feeds."""
from __future__ import annotations
import csv, io, json, math, urllib.parse, urllib.request
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

SOURCE = "Finam Trade API daily candles (account eligibility checked separately)"
UNIVERSE = [
 {"symbol":"LQDT","name":"Liquidity fund","asset_class":"cash_proxy"},
 {"symbol":"SBMM","name":"Money market fund","asset_class":"cash_proxy"},
 {"symbol":"TMOS","name":"MOEX equity index fund","asset_class":"equity_russia"},
 {"symbol":"AKMM","name":"Money market fund","asset_class":"cash_proxy"},
 {"symbol":"AKME","name":"Mixed asset fund","asset_class":"mixed"},
 {"symbol":"TBRU","name":"Russian bonds fund","asset_class":"bonds_russia"},
 {"symbol":"SBRB","name":"Russian bonds fund","asset_class":"bonds_russia"},
 {"symbol":"SBGB","name":"Government bonds fund","asset_class":"bonds_russia"},
 {"symbol":"GOLD","name":"Gold fund","asset_class":"gold"},
 {"symbol":"TGLD","name":"Gold fund","asset_class":"gold"},
 {"symbol":"DIVD","name":"Dividend equity fund","asset_class":"equity_russia"},
 {"symbol":"BCSD","name":"Corporate bonds fund","asset_class":"bonds_russia"},
 {"symbol":"EQMX","name":"MOEX equity index fund","asset_class":"equity_russia"},
 {"symbol":"SBMX","name":"MOEX equity index fund","asset_class":"equity_russia"},
 {"symbol":"SBCB","name":"Corporate bonds fund","asset_class":"bonds_russia"},
]
LOOKBACK,TREND_WINDOW,MAX_HOLDINGS=63,200,4
ESTIMATED_ONE_WAY_COST=0.0010
MIN_COMMON_BARS=220
CASH_KEY="__CASH__"

def parse_yahoo_payload(payload:dict[str,Any],symbol:str,start:date,end:date)->list[dict[str,Any]]:
    chart=payload.get("chart",{})
    if chart.get("error"):
        error=chart["error"]
        raise ValueError(f"yahoo_api_error:{error.get('code','unknown')}")
    result_list=chart.get("result") or []
    if not result_list: raise ValueError("yahoo_empty_chart_result")
    result=result_list[0]
    timestamps=result.get("timestamp") or []
    indicators=result.get("indicators") or {}
    quotes=indicators.get("quote") or []
    if not timestamps or not quotes: raise ValueError("yahoo_missing_ohlcv")
    quote=quotes[0]
    adjusted_rows=indicators.get("adjclose") or []
    adjusted=(adjusted_rows[0].get("adjclose") or []) if adjusted_rows else []
    rows={}
    for i,stamp in enumerate(timestamps):
        try:
            day=datetime.fromtimestamp(int(stamp),timezone.utc).date()
            if day<start or day>end: continue
            o,h,low,raw_close=(quote[k][i] for k in ("open","high","low","close"))
            volume=quote.get("volume",[None]*len(timestamps))[i]
            if any(x is None for x in (o,h,low,raw_close)): continue
            o,h,low,raw_close=(float(x) for x in (o,h,low,raw_close))
            if not all(math.isfinite(x) and x>0 for x in (o,h,low,raw_close)): continue
            if h<max(o,low,raw_close) or low>min(o,h,raw_close): continue
            adj=float(adjusted[i]) if i<len(adjusted) and adjusted[i] is not None else raw_close
            if not math.isfinite(adj) or adj<=0: adj=raw_close
            if volume is not None: volume=float(volume)
            if volume is not None and (not math.isfinite(volume) or volume<0): volume=None
            key=day.isoformat()
            rows[key]={"date":key,"open":o,"high":h,"low":low,"raw_close":raw_close,
                "adjusted_close":adj,"close":adj,"volume":volume,"source":"Yahoo Finance",
                "dividend_adjusted":bool(i<len(adjusted) and adjusted[i] is not None)}
        except (IndexError,TypeError,ValueError,OverflowError):
            continue
    return [rows[k] for k in sorted(rows)]

def _fetch_yahoo(symbol:str,start:date,end:date,timeout:int)->list[dict[str,Any]]:
    ticker=symbol.removesuffix(".US")
    period1=int(datetime.combine(start,time.min,tzinfo=timezone.utc).timestamp())
    period2=int(datetime.combine(end+timedelta(days=1),time.min,tzinfo=timezone.utc).timestamp())
    query=urllib.parse.urlencode({"period1":period1,"period2":period2,"interval":"1d","events":"div,splits","includeAdjustedClose":"true"})
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?{query}"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; PaperPortfolio/1.0)","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as response: payload=json.loads(response.read().decode("utf-8"))
    return parse_yahoo_payload(payload,symbol,start,end)

def _fetch_stooq(symbol:str,start:date,end:date,timeout:int)->list[dict[str,Any]]:
    query=urllib.parse.urlencode({"s":symbol.lower(),"i":"d","d1":start.strftime("%Y%m%d"),"d2":end.strftime("%Y%m%d")})
    req=urllib.request.Request("https://stooq.com/q/d/l/?"+query,headers={"User-Agent":"Mozilla/5.0 (compatible; PaperPortfolio/1.0)"})
    with urllib.request.urlopen(req,timeout=timeout) as response: raw=response.read().decode("utf-8-sig")
    reader=csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or not {"Date","Open","High","Low","Close","Volume"}.issubset(reader.fieldnames):
        raise ValueError("stooq_no_ohlcv_csv_header")
    rows={}
    for item in reader:
        try:
            day=date.fromisoformat(item["Date"])
            if day<start or day>end: continue
            o,h,low,c=(float(item[k]) for k in ("Open","High","Low","Close"))
            vtext=item["Volume"].strip(); volume=float(vtext) if vtext not in ("","N/A") else None
            if not all(math.isfinite(x) and x>0 for x in (o,h,low,c)): continue
            if h<max(o,low,c) or low>min(o,h,c): continue
            if volume is not None and (not math.isfinite(volume) or volume<0): continue
            key=day.isoformat()
            rows[key]={"date":key,"open":o,"high":h,"low":low,"raw_close":c,
                "adjusted_close":c,"close":c,"volume":volume,"source":"Stooq",
                "dividend_adjusted":False}
        except (KeyError,TypeError,ValueError): continue
    return [rows[k] for k in sorted(rows)]

def fetch_daily(symbol:str,start:date,end:date,timeout:int=25)->list[dict[str,Any]]:\n    rows=_fetch_finam(symbol,start,end,timeout)\n    if not rows: raise RuntimeError("Finam:no_valid_daily_bars")\n    return rows

_FINAM_TOKEN=None
_FINAM_BASE="https://api.finam.ru"
_FINAM_MIC="MISX"

def _finam_request(method:str,path:str,token:str|None=None,payload:dict|None=None,timeout:int=25)->dict:
    headers={"Accept":"application/json","Content-Type":"application/json"}
    if token: headers["Authorization"]="Bearer "+token
    req=urllib.request.Request(_FINAM_BASE+path,headers=headers,
        data=json.dumps(payload).encode() if payload is not None else None,method=method)
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Finam HTTP {exc.code}") from None
    except (urllib.error.URLError,TimeoutError) as exc:
        raise RuntimeError(f"Finam network {type(exc).__name__}") from None

def _finam_access_token()->str:
    global _FINAM_TOKEN
    if _FINAM_TOKEN: return _FINAM_TOKEN
    secret=__import__("os").environ.get("FINAM_API_SECRET","").strip()
    if not secret: raise RuntimeError("FINAM_API_SECRET missing")
    response=_finam_request("POST","/v1/sessions",payload={"secret":secret})
    token=response.get("token")
    if not token: raise RuntimeError("Finam auth token missing")
    _FINAM_TOKEN=token
    return token

def parse_finam_bars(payload:dict[str,Any],symbol:str,start:date,end:date)->list[dict[str,Any]]:
    bars=payload.get("bars")
    if not isinstance(bars,list): raise ValueError("finam_bars_missing")
    rows={}
    def value(x):
        if isinstance(x,dict): x=x.get("value")
        return float(x)
    for bar in bars:
        try:
            stamp=bar.get("timestamp")
            day=datetime.fromisoformat(str(stamp).replace("Z","+00:00")).date()
            if day<start or day>end: continue
            o,h,low,close=(value(bar.get(k)) for k in ("open","high","low","close"))
            volume=value(bar.get("volume")) if bar.get("volume") is not None else None
            if not all(math.isfinite(x) and x>0 for x in (o,h,low,close)): continue
            if h<max(o,low,close) or low>min(o,h,close): continue
            if volume is not None and (not math.isfinite(volume) or volume<0): continue
            rows[day.isoformat()]={"date":day.isoformat(),"open":o,"high":h,"low":low,
                "raw_close":close,"adjusted_close":close,"close":close,"volume":volume,
                "source":"Finam Trade API","dividend_adjusted":False}
        except (TypeError,ValueError,KeyError,OverflowError): continue
    return [rows[k] for k in sorted(rows)]

def _fetch_finam(symbol:str,start:date,end:date,timeout:int)->list[dict[str,Any]]:
    # Finam daily candles are limited to roughly one year. Clamp the requested interval.
    effective_start=max(start,end-timedelta(days=365))
    query=urllib.parse.urlencode({"timeframe":"TIME_FRAME_D",
        "interval.start_time":datetime.combine(effective_start,time.min,tzinfo=timezone.utc).isoformat(),
        "interval.end_time":datetime.combine(end+timedelta(days=1),time.min,tzinfo=timezone.utc).isoformat()})
    finam_symbol=f"{symbol}@{_FINAM_MIC}"
    path=f"/v1/instruments/{urllib.parse.quote(finam_symbol,safe='')}/bars?{query}"
    payload=_finam_request("GET",path,token=_finam_access_token(),timeout=timeout)
    return parse_finam_bars(payload,symbol,effective_start,end)

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
    ranked.sort(reverse=True); chosen=[s for _,s in ranked[:MAX_HOLDINGS]]
    weight=1.0/len(chosen) if chosen else 0.0
    return {s:weight for s in chosen}

def build_report(history:dict[str,list[dict[str,Any]]],errors:dict[str,str]|None=None,
                 generated_at:datetime|None=None,allowed_symbols:set[str]|None=None)->dict[str,Any]:
    errors=errors or {}; generated_at=generated_at or datetime.now(timezone.utc)
    eligible={s:r for s,r in history.items() if len(r)>=MIN_COMMON_BARS and (allowed_symbols is None or s in allowed_symbols)}
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
            target=dict(target_assets); target[CASH_KEY]=max(0.0,1.0-sum(target_assets.values()))
            turnover=sum(abs(target.get(s,0.0)-weights.get(s,0.0)) for s in set(target)|set(weights))/2.0
            nav*=max(0.0,1.0-turnover*ESTIMATED_ONE_WAY_COST)
            turnover_total+=turnover; rebalances+=1; weights=target; last_targets=target_assets
        day_return=sum(w*(prices[s][i]/prices[s][i-1]-1.0) for s,w in weights.items() if s!=CASH_KEY)
        nav*=1.0+day_return; daily_returns.append(nav/before-1.0 if before else 0.0); return_dates.append(day)
        peak=max(peak,nav); max_dd=min(max_dd,nav/peak-1.0)
    metrics=_metrics(daily_returns,return_dates); metrics["max_drawdown"]=round(max_dd,6)
    benchmark=[]
    benchmark_metrics=_metrics(benchmark,return_dates) if benchmark else None
    holdings=[{"symbol":s,"weight":round(w,6),"latest_close":eligible[s][-1].get("raw_close",eligible[s][-1]["close"]),"adjusted_close":prices[s][-1],
      "asset_class":next((x["asset_class"] for x in UNIVERSE if x["symbol"]==s),"unknown")} for s,w in sorted(last_targets.items())]
    latest_prices={s:{"date":eligible[s][-1]["date"],"close":eligible[s][-1].get("raw_close",eligible[s][-1]["close"]),"adjusted_close":eligible[s][-1]["close"]} for s in eligible}
    stale=[s for s,x in latest_prices.items() if (generated_at.date()-date.fromisoformat(x["date"])).days>7]
    providers=sorted({row.get("source","unknown") for rows in eligible.values() for row in rows[-1:]})
    return {"status":"READY" if not stale else "DATA_STALE","generated_at_utc":generated_at.isoformat(),"source":SOURCE,
      "providers_used":providers,"provider_by_symbol":{s:eligible[s][-1].get("source","unknown") for s in eligible},"market_scope":"MOEX ETFs/funds account-verified against Finam; native exchange instruments",
      "portfolio_model":{"name":"Global 63-session momentum + 200-session trend","initial_nav_index":100.0,
        "currency":"NOT_APPLICABLE_INDEX_UNITS","rebalance":"monthly, using prior completed daily close",
        "selection":"up to four Finam-account-verified eligible assets with positive 63-session momentum and close above 200-session SMA",
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
      "safety":safety,"limitations":["Daily closes are not live quotes or executable bid/ask.",
        "Dividend-adjusted close is used when the provider supplies it; Stooq fallback is price-only.",
        "US-listed ETF proxies are not direct ownership of every underlying market.",
        "The 100-point NAV is a normalized research index, not user capital or currency.",
        "Historical results are not a forecast or proof of profitability."]}

def download_universe(start:date,end:date,symbols:set[str]|None=None)->tuple[dict[str,list[dict[str,Any]]],dict[str,str]]:
    history,errors={},{}
    for item in UNIVERSE:
        if symbols is not None and item["symbol"] not in symbols: continue
        symbol=item["symbol"]
        try:
            rows=fetch_daily(symbol,start,end)
            if len(rows)<MIN_COMMON_BARS: errors[symbol]=f"insufficient_valid_bars:{len(rows)}"
            else: history[symbol]=rows
        except Exception as exc: errors[symbol]=f"{type(exc).__name__}:{str(exc)[:220]}"
    return history,errors
