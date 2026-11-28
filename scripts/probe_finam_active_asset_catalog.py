#!/usr/bin/env python3
"""Read-only Finam active asset catalog probe with cursor pagination."""
import json,os,sys,time
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
BASE="https://api.finam.ru"
def call(path,token=None,payload=None,method="GET"):
 headers={"Accept":"application/json","Content-Type":"application/json"}
 if token:headers["Authorization"]="Bearer "+token
 req=Request(BASE+path,headers=headers,data=json.dumps(payload).encode() if payload is not None else None,method=method)
 for attempt in range(4):
  try:
   with urlopen(req,timeout=25) as r:return json.loads(r.read().decode())
  except HTTPError as e:
   if e.code in (429,500,502,503,504) and attempt<3:
    time.sleep(2**attempt);continue
   raise RuntimeError(f"Finam HTTP {e.code}") from None
  except (URLError,TimeoutError) as e:
   if attempt<3:time.sleep(2**attempt);continue
   raise RuntimeError(f"Finam network {type(e).__name__}") from None
def main():
 secret=os.getenv("FINAM_API_SECRET","").strip()
 if not secret:print("CATALOG_PROBE=FAIL_MISSING_SECRET");return 2
 auth=call("/v1/sessions",payload={"secret":secret},method="POST")
 token=auth.get("token")
 if not token:print("CATALOG_PROBE=FAIL_TOKEN");return 2
 assets=[];cursor="0";seen=set();pages=0
 while cursor and pages<500:
  if cursor in seen:raise RuntimeError("catalog_cursor_loop")
  seen.add(cursor);pages+=1
  data=call("/v1/assets/all?"+urlencode({"cursor":cursor,"only_active":"true"}),token)
  page=data.get("assets")
  if not isinstance(page,list):raise RuntimeError("catalog_response_malformed")
  assets.extend(page)
  nxt=data.get("next_cursor")
  cursor=str(nxt) if nxt else ""
  if cursor:time.sleep(.35)
 if cursor:raise RuntimeError("catalog_page_cap_reached")
 types={};mics={};funds=[]
 for a in assets:
  typ=str(a.get("type") or "UNKNOWN");mic=str(a.get("mic") or "UNKNOWN")
  types[typ]=types.get(typ,0)+1;mics[mic]=mics.get(mic,0)+1
  desc=(str(a.get("name") or "")+" "+typ+" "+str(a.get("ticker") or "")).lower()
  if any(k in desc for k in ("etf","fund","фонд","биржевой фонд","investment fund","паевой")):
   funds.append({"symbol":a.get("symbol"),"ticker":a.get("ticker"),"mic":mic,"type":typ,"name":str(a.get("name") or "")[:120]})
 print("CATALOG_PROBE=SUCCESS total_assets="+str(len(assets))+" pages="+str(pages))
 print("ASSET_TYPE_COUNTS="+json.dumps(types,ensure_ascii=False,sort_keys=True))
 print("MIC_COUNTS="+json.dumps(mics,ensure_ascii=False,sort_keys=True))
 print("FUND_CANDIDATES="+json.dumps(funds[:300],ensure_ascii=False))
 return 0
if __name__=="__main__":sys.exit(main())
