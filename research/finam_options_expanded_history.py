#!/usr/bin/env python3
"""Read-only Finam option history collector: nearby expiries/strikes, OHLCV only."""
import json, os, re, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from decimal import Decimal, InvalidOperation
import requests

BASE="https://api.finam.ru"; TIMEOUT=20
UNDERLYINGS=["SBER@MISX","GAZP@MISX","LKOH@MISX","ROSN@MISX","MOEX@MISX"]
def val(x): return x.get("value") if isinstance(x,dict) else x
def dec(x):
    try:
        d=Decimal(str(val(x))); return d if d.is_finite() else None
    except (InvalidOperation,TypeError,ValueError): return None
def date(x):
    # Finam may wrap scalar fields in {"value": ...}; date components may be wrapped too.
    if isinstance(x, dict) and isinstance(x.get("value"), dict):
        x = x["value"]
    if isinstance(x, str):
        try: return datetime.fromisoformat(x.replace("Z", "+00:00")).date().isoformat()
        except ValueError: return None
    if not isinstance(x, dict): return None
    try:
        return f"{int(val(x['year'])):04d}-{int(val(x['month'])):02d}-{int(val(x['day'])):02d}"
    except (KeyError, TypeError, ValueError): return None

def option_type(x):
    raw = val(x)
    text = str(raw or "").upper()
    if "CALL" in text: return "TYPE_CALL"
    if "PUT" in text: return "TYPE_PUT"
    return None
class API:
    def __init__(self,secret):
        self.s=requests.Session();self.s.headers["User-Agent"]="finam-options-history-research/1.0"
        r=self.s.post(BASE+"/v1/sessions",json={"secret":secret},timeout=TIMEOUT)
        if r.status_code!=200:raise RuntimeError("auth_http_"+str(r.status_code))
        token=r.json().get("token")
        if not token:raise RuntimeError("auth_token_missing")
        self.s.headers["Authorization"]="Bearer "+token
    def get(self,path,params=None):
        # Stay below Finam REST limit of 200 requests/minute across the expanded probe.
        time.sleep(0.36)
        try:r=self.s.get(BASE+path,params=params,timeout=TIMEOUT)
        except requests.RequestException as e:raise RuntimeError("network_"+type(e).__name__) from None
        if r.status_code!=200:return r.status_code,None
        try:return r.status_code,r.json()
        except ValueError:return r.status_code,None
def bars(api,symbol,tf,start,end):
    st,data=api.get(f"/v1/instruments/{quote(symbol,safe='')}/bars",{"timeframe":tf,"interval.start_time":start,"interval.end_time":end})
    raw=(data or {}).get("bars") if st==200 else None
    if not isinstance(raw,list):return {"http_status":st,"available":False,"series":[]}
    out=[]
    for b in raw:
        try:
            o,h,l,c,v=[dec(b.get(k)) for k in ("open","high","low","close","volume")]
            if None in (o,h,l,c,v) or min(o,h,l,c)<=0 or v<0 or h<max(o,c,l) or l>min(o,c,h):continue
            out.append({"timestamp":str(b.get("timestamp")),"open":str(o),"high":str(h),"low":str(l),"close":str(c),"volume":str(v),"is_data_snapshot":bool(b.get("is_data_snapshot"))})
        except Exception:continue
    out.sort(key=lambda x:x["timestamp"])
    return {"http_status":st,"available":True,"bars_count":len(raw),"valid_ohlc_bars":len(out),"first_timestamp":out[0]["timestamp"] if out else None,"last_timestamp":out[-1]["timestamp"] if out else None,"series":out}
def diagnose_chain(opts, today):
    from collections import Counter
    types=Counter(); expiries=Counter(); rejected=Counter(); dtes=[]
    for o in opts or []:
        if not isinstance(o,dict): rejected["not_object"]+=1; continue
        typ=option_type(o.get("type")); types[typ or str(val(o.get("type")))]+=1
        exp=date(o.get("expiration_last_day")) or date(o.get("expiration_first_day"))
        strike=dec(o.get("strike"))
        if not exp: rejected["date_unparsed"]+=1; continue
        try: dte=(datetime.fromisoformat(exp).date()-today).days
        except ValueError: rejected["date_invalid"]+=1; continue
        expiries[exp]+=1; dtes.append(dte)
        if strike is None: rejected["strike_unparsed"]+=1
        elif typ not in ("TYPE_CALL","TYPE_PUT"): rejected["type_unrecognized"]+=1
        elif not 15<=dte<=365: rejected["outside_15_365_dte"]+=1
    return {
        "chain_total":len(opts or []),
        "type_counts":dict(types),
        "expiry_date_count":len(expiries),
        "expiry_dates_earliest_20":sorted(expiries.items())[:20],
        "expiry_dates_latest_10":sorted(expiries.items())[-10:],
        "dte_min":min(dtes) if dtes else None,
        "dte_max":max(dtes) if dtes else None,
        "contracts_with_expiry_15_365_dte":sum(n for e,n in expiries.items() if 15 <= (datetime.fromisoformat(e).date()-today).days <= 365),
        "rejection_counts":dict(rejected)
    }

def third_wednesday(year, month):
    first_day = datetime(year, month, 1).date()
    days_to_wednesday = (2 - first_day.weekday()) % 7
    return first_day + timedelta(days=days_to_wednesday + 14)

def options_chain(api, underlying, today):
    """Probe exact monthly expiries (third Wednesday), then retry with observed roots."""
    path = f"/v1/assets/{quote(underlying,safe='')}/options"
    base_status, base_payload = api.get(path)
    base_rows = (base_payload or {}).get("options", []) if base_status == 200 else []
    if not isinstance(base_rows, list):
        base_rows = []

    roots = sorted({
        match.group(1)
        for option in base_rows if isinstance(option, dict)
        for symbol in [str(option.get("symbol", "")).split("@", 1)[0]]
        for match in [re.match(r"^([A-Z]+)\d", symbol)]
        if match
    })
    first = today + timedelta(days=15)
    last = today + timedelta(days=365)
    month = first.replace(day=1)
    collected = {}
    for option in base_rows:
        if isinstance(option, dict) and option.get("symbol"):
            collected[option["symbol"]] = option

    monthly = [{
        "query_kind": "unfiltered_baseline", "root": None,
        "http_status": base_status, "contracts_returned": len(base_rows),
        "expiry_dates": sorted({date(o.get("expiration_last_day")) or date(o.get("expiration_first_day")) for o in base_rows if isinstance(o, dict)} - {None}),
    }]
    while month <= last:
        expiry = third_wednesday(month.year, month.month)
        if first <= expiry <= last:
            common = {
                "expiration_date.year": str(expiry.year),
                "expiration_date.month": str(expiry.month),
                "expiration_date.day": str(expiry.day),
            }
            status, payload = api.get(path, common)
            rows = (payload or {}).get("options", []) if status == 200 else []
            if not isinstance(rows, list):
                rows = []
            for option in rows:
                if isinstance(option, dict) and option.get("symbol"):
                    collected[option["symbol"]] = option
            monthly.append({
                "query_kind": "exact_expiry_no_root", "root": None,
                "requested_expiry": expiry.isoformat(),
                "http_status": status, "contracts_returned": len(rows),
                "expiry_dates": sorted({date(o.get("expiration_last_day")) or date(o.get("expiration_first_day")) for o in rows if isinstance(o, dict)} - {None}),
            })
            # Only retry with observed symbol roots when the exact-expiry control is empty.
            if not rows:
                for root in roots:
                    params = dict(common)
                    params["root"] = root
                    root_status, root_payload = api.get(path, params)
                    root_rows = (root_payload or {}).get("options", []) if root_status == 200 else []
                    if not isinstance(root_rows, list):
                        root_rows = []
                    for option in root_rows:
                        if isinstance(option, dict) and option.get("symbol"):
                            collected[option["symbol"]] = option
                    monthly.append({
                        "query_kind": "exact_expiry_root_probe", "root": root,
                        "requested_expiry": expiry.isoformat(),
                        "http_status": root_status, "contracts_returned": len(root_rows),
                        "expiry_dates": sorted({date(o.get("expiration_last_day")) or date(o.get("expiration_first_day")) for o in root_rows if isinstance(o, dict)} - {None}),
                    })
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return list(collected.values()), monthly, roots, base_status

def select(opts,spot,today):
    parsed=[]
    for o in opts or []:
        if not isinstance(o,dict) or not o.get("symbol"):continue
        strike=dec(o.get("strike"));exp=date(o.get("expiration_last_day")) or date(o.get("expiration_first_day"));typ=option_type(o.get("type"))
        if strike is None or not exp or typ not in ("TYPE_CALL","TYPE_PUT"):continue
        try:dte=(datetime.fromisoformat(exp).date()-today).days
        except ValueError:continue
        if 15<=dte<=365:parsed.append({"symbol":o["symbol"],"type":typ,"strike":str(strike),"expiry":exp,"dte":dte,"contract_size":val(o.get("contract_size")),"multiplier":val(o.get("multiplier")),"dist":abs(float(strike)-float(spot))})
    exps=sorted(set(x["expiry"] for x in parsed),key=lambda e:(datetime.fromisoformat(e).date()-today).days)[:2]
    selected=[]
    for e in exps:
        for typ in ("TYPE_CALL","TYPE_PUT"):
            side=sorted([x for x in parsed if x["expiry"]==e and x["type"]==typ],key=lambda x:x["dist"])
            selected.extend(side[:3])
    for x in selected:x.pop("dist",None)
    return selected
def main():
    secret=os.environ.get("FINAM_API_SECRET")
    if not secret:raise RuntimeError("FINAM_API_SECRET_missing")
    symbols=[x.strip() for x in os.environ.get("OPTION_UNDERLYINGS",",".join(UNDERLYINGS)).split(",") if x.strip()]
    now=datetime.now(timezone.utc);today=now.date();api=API(secret)
    start30=(now-timedelta(days=30)).isoformat(timespec="seconds").replace("+00:00","Z")
    start365=(now-timedelta(days=365)).isoformat(timespec="seconds").replace("+00:00","Z")
    end=(now+timedelta(minutes=1)).isoformat(timespec="seconds").replace("+00:00","Z")
    out={"as_of_utc":now.isoformat(),"mode":"read_only_expanded_options_ohlcv_root_probe_365d","underlyings":{},"safety":{"market_data_get_only":True,"account_endpoints_called":False,"orders_or_cancel_called":False,"secret_logged":False},"limitations":["OHLC bars are trade-derived aggregates, not executable bid/ask quotes.","Contracts selected from current chain/spot; historical selection bias remains.","Near-ATM contracts and up to two expiries only; exploratory sample."]}
    for u in symbols:
        item={"status":"ok"}
        try:
            qs,q=api.get(f"/v1/instruments/{quote(u,safe='')}/quotes/latest");q=(q or {}).get("quote",{});spot=dec(q.get("last"))
            opts, monthly_chain_queries, root_candidates, baseline_chain_http = options_chain(api,u,today)
            if spot is None or not opts:item.update({"status":"unavailable","quote_http":qs,"monthly_chain_queries":monthly_chain_queries})
            else:
                selected=select(opts,spot,today)
                schema_sample=[]
                for raw_option in opts[:3]:
                    if isinstance(raw_option,dict):
                        schema_sample.append({"keys":sorted(raw_option.keys()),"type_value":val(raw_option.get("type")),"type_python":type(raw_option.get("type")).__name__,"expiration_last_day_python":type(raw_option.get("expiration_last_day")).__name__,"expiration_last_day_raw":raw_option.get("expiration_last_day"),"expiration_first_day_raw":raw_option.get("expiration_first_day"),"expiration_last_day_normalized":date(raw_option.get("expiration_last_day")),"expiration_first_day_normalized":date(raw_option.get("expiration_first_day")),"strike_raw":raw_option.get("strike"),"strike_normalized":str(dec(raw_option.get("strike"))) if dec(raw_option.get("strike")) is not None else None,"symbol":raw_option.get("symbol")})
                item.update({"option_chain_diagnostics":diagnose_chain(opts,today),"monthly_chain_queries":monthly_chain_queries,"root_candidates_from_symbols":root_candidates,"baseline_chain_http":baseline_chain_http,"option_schema_sample":schema_sample,"selection_status":"ok" if selected else "no_contracts_after_normalization","spot_quote":{k:val(q.get(k)) for k in ("timestamp","bid","ask","last","bid_size","ask_size")},"chain_count":len(opts),"contracts_selected":len(selected),"underlying_bars":{"h1":bars(api,u,"TIME_FRAME_H1",start30,end),"d1":bars(api,u,"TIME_FRAME_D",start365,end)},"contract_data":[]})
                for c in selected:
                    c["history"]={"m5":bars(api,c["symbol"],"TIME_FRAME_M5",start30,end),"h1":bars(api,c["symbol"],"TIME_FRAME_H1",start30,end),"d1":bars(api,c["symbol"],"TIME_FRAME_D",start365,end)}
                    item["contract_data"].append(c)
        except Exception as e:item.update({"status":"error","error_type":type(e).__name__})
        out["underlyings"][u]=item
    path=os.environ.get("OUTPUT_JSON","finam-options-expanded-history.json");Path(path).write_text(json.dumps(out,ensure_ascii=False,indent=2))
    n=sum(len(x.get("contract_data",[])) for x in out["underlyings"].values());nb=sum(len(c.get("history",{}).get(tf,{}).get("series",[])) for x in out["underlyings"].values() for c in x.get("contract_data",[]) for tf in ("m5","h1","d1"))
    print(json.dumps({"status":"completed","symbols":len(symbols),"contracts":n,"bars":nb,"output":path}))
    if not n:sys.exit(2)
if __name__=="__main__":
    try:main()
    except Exception as e:print("OPTIONS HISTORY FAILED: "+type(e).__name__);sys.exit(1)
