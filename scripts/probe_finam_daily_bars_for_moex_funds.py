#!/usr/bin/env python3
"""Read-only Finam daily-bars feasibility probe for account-approved MOEX fund candidates."""
import json,os,sys
from datetime import datetime,timezone,timedelta
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import quote,urlencode
BASE="https://api.finam.ru"
CANDIDATES=("LQDT","SBMM","TMOS","AKMM","AKME","TBRU","SBRB","SBGB","GOLD","TGLD","DIVD","BCSD","EQMX","SBMX","SBCB")
MIC="MISX"
def req(method,path,token=None,body=None):
 h={"Accept":"application/json","Content-Type":"application/json"}
 if token:h["Authorization"]="Bearer "+token
 r=Request(BASE+path,headers=h,data=json.dumps(body).encode() if body else None,method=method)
 try:
  with urlopen(r,timeout=25) as x:return json.loads(x.read().decode())
 except HTTPError as e:raise RuntimeError("HTTP_"+str(e.code)) from None
 except (URLError,TimeoutError) as e:raise RuntimeError("NETWORK_"+type(e).__name__) from None
def main():
 secret=os.getenv("FINAM_API_SECRET","").strip()
 if not secret:print("BARS_PROBE=FAIL_MISSING_SECRET");return 2
 token=req("POST","/v1/sessions",body={"secret":secret}).get("token")
 if not token:print("BARS_PROBE=FAIL_TOKEN");return 2
 end=datetime.now(timezone.utc);start=end-timedelta(days=360)
 q=urlencode({"timeframe":"TIME_FRAME_D","interval.start_time":start.isoformat(),"interval.end_time":end.isoformat()})
 counts={};details=[]
 for t in CANDIDATES:
  symbol=f"{t}@{MIC}"
  try:
   data=req("GET",f"/v1/instruments/{quote(symbol,safe='')} /bars?{q}".replace(" ",""),token)
   bars=data.get("bars",[])
   details.append({"ticker":t,"bars":len(bars),"first":bars[0].get("timestamp") if bars else None,"last":bars[-1].get("timestamp") if bars else None})
   counts["OK"]=counts.get("OK",0)+1
  except RuntimeError as e:
   counts[str(e)]=counts.get(str(e),0)+1
 print("BARS_PROBE=COMPLETE candidates="+str(len(CANDIDATES))+" successful="+str(counts.get("OK",0)))
 print("ERROR_COUNTS="+json.dumps(counts,sort_keys=True))
 print("BAR_SUMMARY="+json.dumps(details,ensure_ascii=False))
 return 0
if __name__=="__main__":sys.exit(main())
