#!/usr/bin/env python3
"""Refresh the experimental portfolio allowlist from account-scoped Finam READ-ONLY data."""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE="https://api.finam.ru"
TARGETS={"SPY","QQQ","IWM","EFA","EEM","VGK","EWJ","INDA","TLT","IEF","GLD","DBC","VNQ","SHY"}
US_MICS={"XNAS","XNYS","ARCX","BATS","XASE","NASDAQ","NYSE","AMEX"}
OUT=Path("experimental_portfolio/finam_allowlist.json")

def api(method,path,token=None,params=None,payload=None):
    if params:
        path += "?" + "&".join(f"{quote(k)}={quote(str(v))}" for k,v in params.items())
    headers={"Accept":"application/json","Content-Type":"application/json"}
    if token: headers["Authorization"]="Bearer "+token
    req=Request(BASE+path,headers=headers,data=json.dumps(payload).encode() if payload is not None else None,method=method)
    try:
        with urlopen(req,timeout=20) as res: return json.loads(res.read().decode())
    except HTTPError as e: raise RuntimeError(f"Finam HTTP {e.code}") from None
    except (URLError,TimeoutError) as e: raise RuntimeError(f"Finam network error ({type(e).__name__})") from None

def enum(v):
    return v.get("value") if isinstance(v,dict) else v

def fetch_assets(token):
    # The active tradeable catalog is a single response; avoid scanning the
    # paginated all-assets catalog, which includes archived/indicative assets.
    data=api("GET","/v1/assets",token)
    assets=data.get("assets")
    if not isinstance(assets,list): raise RuntimeError("Finam assets list malformed")
    return assets

def refresh():
    secret=os.getenv("FINAM_API_SECRET","").strip()
    account=os.getenv("FINAM_ACCOUNT_ID","").strip()
    result={"schema_version":1,"account_scope":"Finam account (identifier not stored)",
      "verification_source":"Finam Trade API account-scoped GET asset params",
      "last_verified":datetime.now(timezone.utc).isoformat(),"instruments":[],
      "policy":"Only exact candidate ticker with verified account tradability and LONG availability; fail closed."}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    if not secret or not account:
        result["verification_source"]="SECRETS_MISSING_FAIL_CLOSED"
        OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        print("ALLOWLIST_REFRESH=FAIL_CLOSED_SECRETS_MISSING")
        return 2
    try:
        auth=api("POST","/v1/sessions",payload={"secret":secret})
        token=auth.get("token")
        if not token: raise RuntimeError("Finam token missing")
        assets=fetch_assets(token)
        matched={}
        for a in assets:
            ticker=str(a.get("ticker") or "").upper()
            mic=str(a.get("mic") or "").upper()
            if ticker in TARGETS and mic in US_MICS:
                matched.setdefault(ticker,[]).append(a)
        eligible=[]
        failures=0
        for ticker in sorted(TARGETS):
            candidates=matched.get(ticker,[])
            # Ambiguous account instruments are not automatically approved.
            if len(candidates)!=1:
                if candidates: failures+=1
                continue
            asset=candidates[0]; symbol=f'{asset.get("ticker")}@{asset.get("mic")}'
            params=api("GET",f"/v1/assets/{quote(symbol,safe='')}/params",token,{"account_id":account})
            long_status=enum(params.get("longable"))
            is_tradable=params.get("is_tradable") is True
            if is_tradable and long_status in ("AVAILABLE",1,"1"):
                eligible.append({"symbol":ticker+".US","finam_symbol":symbol,
                    "account_buy_permission":"BUY_ALLOWED","verified_account_access":True,
                    "verified_at":result["last_verified"],"is_tradable":True,
                    "longable":str(long_status),"trade_lot_size":params.get("trade_lot_size")})
            time.sleep(.35)
        result["instruments"]=eligible
        result["verification_source"]="Finam account-scoped API; verified individually"
        result["last_verified"]=datetime.now(timezone.utc).isoformat()
        OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        print(f"ALLOWLIST_REFRESH=SUCCESS eligible={len(eligible)} candidates={len(TARGETS)} ambiguous={failures}")
        print("Eligible symbols:",", ".join(x["symbol"] for x in eligible) if eligible else "none; portfolio remains cash")
        return 0
    except Exception as exc:
        # Clear eligibility on any error rather than retain stale approvals.
        result["verification_source"]="FINAM_CHECK_FAILED_FAIL_CLOSED"
        result["error"]=str(exc)[:160]
        OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        print("ALLOWLIST_REFRESH=FAILED_FAIL_CLOSED ("+str(exc)[:160]+")")
        return 3

if __name__=="__main__": sys.exit(refresh())
