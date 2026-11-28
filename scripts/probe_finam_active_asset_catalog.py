#!/usr/bin/env python3
"""Read-only Finam active asset catalog probe. Prints sanitized ETF/fund candidates."""
import json,os,sys
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
BASE="https://api.finam.ru"
def call(path,token=None):
 h={"Accept":"application/json"}
 if token:h["Authorization"]="Bearer "+token
 req=Request(BASE+path,headers=h)
 try:
  with urlopen(req,timeout=25) as r:return json.loads(r.read().decode())
 except HTTPError as e:raise RuntimeError(f"Finam HTTP {e.code}") from None
 except (URLError,TimeoutError) as e:raise RuntimeError(f"Finam network {type(e).__name__}") from None
def main():
 secret=os.getenv("FINAM_API_SECRET","").strip()
 if not secret: print("CATALOG_PROBE=FAIL_MISSING_SECRET");return 2
 auth=call("/v1/sessions") if False else None
 req=Request(BASE+"/v1/sessions",headers={"Accept":"application/json","Content-Type":"application/json"},data=json.dumps({"secret":secret}).encode(),method="POST")
 try:
  with urlopen(req,timeout=20) as r:token=json.loads(r.read().decode()).get("token")
 except HTTPError as e:print(f"CATALOG_PROBE=FAIL_AUTH_HTTP_{e.code}");return 2
 if not token: print("CATALOG_PROBE=FAIL_TOKEN");return 2
 data=call("/v1/assets",token)
 assets=data.get("assets")
 if not isinstance(assets,list):print("CATALOG_PROBE=FAIL_BAD_RESPONSE");return 2
 types={}; mics={}; funds=[]
 for a in assets:
  typ=str(a.get("type") or "UNKNOWN");mic=str(a.get("mic") or "UNKNOWN")
  types[typ]=types.get(typ,0)+1;mics[mic]=mics.get(mic,0)+1
  desc=(str(a.get("name") or "")+" "+typ).lower()
  if any(k in desc for k in ("etf","fund","фонд","биржевой фонд","investment fund")):
   funds.append({"symbol":a.get("symbol"),"ticker":a.get("ticker"),"mic":mic,"type":typ,"name":str(a.get("name") or "")[:120]})
 print("CATALOG_PROBE=SUCCESS total_assets="+str(len(assets)))
 print("ASSET_TYPE_COUNTS="+json.dumps(types,ensure_ascii=False,sort_keys=True))
 print("MIC_COUNTS="+json.dumps(mics,ensure_ascii=False,sort_keys=True))
 print("FUND_CANDIDATES="+json.dumps(funds[:300],ensure_ascii=False))
 return 0
if __name__=="__main__":sys.exit(main())
