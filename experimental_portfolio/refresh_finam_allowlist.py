#!/usr/bin/env python3
"""Refresh the experimental portfolio allowlist using direct account-scoped Finam checks."""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE="https://api.finam.ru"
TARGETS={"SPY","QQQ","IWM","EFA","EEM","VGK","EWJ","INDA","TLT","IEF","GLD","DBC","VNQ","SHY"}
# Candidate MICs for US ETF listings. Each ticker is checked individually.
MIC_CANDIDATES=("ARCX","XNAS","XNYS","XASE")
OUT=Path("experimental_portfolio/finam_allowlist.json")

class FinamHTTPError(RuntimeError):
    def __init__(self,status):
        self.status=status
        super().__init__(f"Finam HTTP {status}")

def api(method,path,token=None,params=None,payload=None):
    if params:
        path += "?" + urlencode(params)
    headers={"Accept":"application/json","Content-Type":"application/json"}
    if token: headers["Authorization"]="Bearer "+token
    req=Request(BASE+path,headers=headers,data=json.dumps(payload).encode() if payload is not None else None,method=method)
    try:
        with urlopen(req,timeout=20) as res: return json.loads(res.read().decode())
    except HTTPError as e: raise FinamHTTPError(e.code) from None
    except (URLError,TimeoutError) as e: raise RuntimeError(f"Finam network error ({type(e).__name__})") from None

def enum(v):
    return v.get("value") if isinstance(v,dict) else v

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
        eligible=[]; errors=0
        for ticker in sorted(TARGETS):
            available=[]
            for mic in MIC_CANDIDATES:
                symbol=f"{ticker}@{mic}"
                try:
                    params=api("GET",f"/v1/assets/{quote(symbol,safe='')}/params",token,{"account_id":account})
                except FinamHTTPError as exc:
                    if exc.status in (400,404):
                        continue  # listing absent/not recognized for this account
                    raise
                long_status=enum(params.get("longable"))
                if params.get("is_tradable") is True and long_status in ("AVAILABLE",1,"1"):
                    available.append((symbol,params))
                time.sleep(.25)
            # If multiple account-enabled listings exist, block rather than guess.
            if len(available)==1:
                symbol,params=available[0]
                eligible.append({"symbol":ticker+".US","finam_symbol":symbol,
                    "account_buy_permission":"BUY_ALLOWED","verified_account_access":True,
                    "verified_at":result["last_verified"],"is_tradable":True,
                    "longable":str(enum(params.get("longable"))),"trade_lot_size":params.get("trade_lot_size")})
            elif len(available)>1:
                errors+=1
        result["instruments"]=eligible
        result["verification_source"]="Finam account-scoped API; direct per-symbol checks"
        result["last_verified"]=datetime.now(timezone.utc).isoformat()
        OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        print(f"ALLOWLIST_REFRESH=SUCCESS eligible={len(eligible)} candidates={len(TARGETS)} ambiguous={errors}")
        print("Eligible symbols:",", ".join(x["symbol"] for x in eligible) if eligible else "none; portfolio remains cash")
        return 0
    except Exception as exc:
        # Clear eligibility on any unexpected API/network error.
        result["verification_source"]="FINAM_CHECK_FAILED_FAIL_CLOSED"
        result["error"]=str(exc)[:160]
        OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        print("ALLOWLIST_REFRESH=FAILED_FAIL_CLOSED ("+str(exc)[:160]+")")
        return 3

if __name__=="__main__": sys.exit(refresh())
