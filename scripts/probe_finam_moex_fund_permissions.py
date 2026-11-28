#!/usr/bin/env python3
"""Read-only account permission probe for candidate MOEX exchange-traded funds."""
import json,os,time
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import quote,urlencode
BASE="https://api.finam.ru"
CANDIDATES=("LQDT","SBMM","TMOS","AKMM","AKME","TBRU","SBRB","SBGB","GOLD","TGLD","DIVD","BCSD","EQMX","SBMX","SBCB","FXRL","RUBB","RUSB","RUSE","AMRE","AMRU","AMRB","AMRH","AMRS","AMRA","AMRE","AMRW","AMNY","AMNR")
MIC="MISX"
def call(method,path,token=None,body=None):
 h={"Accept":"application/json","Content-Type":"application/json"}
 if token:h["Authorization"]="Bearer "+token
 req=Request(BASE+path,headers=h,data=json.dumps(body).encode() if body is not None else None,method=method)
 try:
  with urlopen(req,timeout=20) as r:return json.loads(r.read().decode())
 except HTTPError as e:raise RuntimeError(f"HTTP_{e.code}") from None
 except (URLError,TimeoutError) as e:raise RuntimeError("NETWORK_"+type(e).__name__) from None
def main():
 secret=os.getenv("FINAM_API_SECRET","").strip();account=os.getenv("FINAM_ACCOUNT_ID","").strip()
 if not secret or not account: print("MOEX_FUND_PROBE=FAIL_CLOSED_SECRETS_MISSING");return 2
 token=call("POST","/v1/sessions",body={"secret":secret}).get("token")
 if not token: print("MOEX_FUND_PROBE=FAIL_TOKEN");return 2
 counts={};found=0;eligible=[];errors=0
 for ticker in sorted(set(CANDIDATES)):
  symbol=f"{ticker}@{MIC}"
  try:
   p=call("GET",f"/v1/assets/{quote(symbol,safe='')}?{urlencode({'account_id':account})}",token)
   found+=1
   params=call("GET",f"/v1/assets/{quote(symbol,safe='')}/params?{urlencode({'account_id':account})}",token)
   status=params.get("longable")
   if isinstance(status,dict):status=status.get("value")
   key=str(status or "MISSING");counts[key]=counts.get(key,0)+1
   if params.get("is_tradable") is True and status in ("AVAILABLE",1,"1"):
    eligible.append(ticker)
  except RuntimeError as e:
   k=str(e);counts[k]=counts.get(k,0)+1
   if not k.startswith(("HTTP_400","HTTP_404")):errors+=1
  time.sleep(.2)
 print("MOEX_FUND_PROBE=COMPLETE candidates="+str(len(set(CANDIDATES)))+" assets_found="+str(found)+" eligible="+str(len(eligible))+" errors="+str(errors))
 print("RESULT_COUNTS="+json.dumps(counts,sort_keys=True))
 print("ELIGIBLE_TICKERS="+",".join(eligible) if eligible else "ELIGIBLE_TICKERS=none")
 return 0
if __name__=="__main__":raise SystemExit(main())
