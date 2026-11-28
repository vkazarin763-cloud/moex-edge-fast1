#!/usr/bin/env python3
"""Read-only validation of daily Finam bars for account-eligible MOEX funds."""
import json,os,sys,math
from datetime import datetime,timezone,timedelta
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import quote,urlencode
BASE="https://api.finam.ru"
CANDIDATES=("AKME","AKMM","AMNR","AMNY","AMRE","AMRH","BCSD","DIVD","EQMX","GOLD","LQDT","SBCB","SBGB","SBMM","SBMX","SBRB","TBRU","TGLD","TMOS")
MIC="MISX"
def req(method,path,token=None,body=None):
 h={"Accept":"application/json","Content-Type":"application/json"}
 if token:h["Authorization"]="Bearer "+token
 r=Request(BASE+path,headers=h,data=json.dumps(body).encode() if body is not None else None,method=method)
 try:
  with urlopen(r,timeout=25) as x:return json.loads(x.read().decode())
 except HTTPError as e:raise RuntimeError("HTTP_"+str(e.code)) from None
 except (URLError,TimeoutError) as e:raise RuntimeError("NETWORK_"+type(e).__name__) from None
def main():
 secret=os.getenv("FINAM_API_SECRET","").strip()
 if not secret:print("BARS_VALIDATE=FAIL_MISSING_SECRET");return 2
 token=req("POST","/v1/sessions",body={"secret":secret}).get("token")
 if not token:print("BARS_VALIDATE=FAIL_TOKEN");return 2
 end=datetime.now(timezone.utc);start=end-timedelta(days=350)
 q=urlencode({"timeframe":"TIME_FRAME_D","interval.start_time":start.isoformat(),"interval.end_time":end.isoformat()})
 outcomes=[];totals={"assets":len(CANDIDATES),"success":0,"errors":0,"valid_bars":0,"invalid_bars":0}
 for t in CANDIDATES:
  symbol=f"{t}@{MIC}"
  try:
   data=req("GET",f"/v1/instruments/{quote(symbol,safe='')}/bars?{q}",token)
   bars=data.get("bars",[])
   valid=0;bad=0;dates=[]
   for b in bars:
    try:
     vals=[float(b[k].get("value") if isinstance(b[k],dict) else b[k]) for k in ("open","high","low","close")]
     if not all(math.isfinite(x) and x>0 for x in vals):raise ValueError()
     o,h,l,c=vals
     if h<max(o,l,c) or l>min(o,h,c):raise ValueError()
     valid+=1;dates.append(str(b.get("timestamp") or b.get("date") or ""))
    except Exception:bad+=1
   totals["success"]+=1;totals["valid_bars"]+=valid;totals["invalid_bars"]+=bad
   outcomes.append({"ticker":t,"bars_total":len(bars),"bars_valid":valid,"bars_invalid":bad,"first":dates[0] if dates else None,"last":dates[-1] if dates else None,"response_keys":sorted(data.keys())})
  except RuntimeError as e:
   totals["errors"]+=1;outcomes.append({"ticker":t,"error":str(e)})
 print("BARS_VALIDATE=COMPLETE "+json.dumps(totals,sort_keys=True))
 print("BAR_OUTCOMES="+json.dumps(outcomes,ensure_ascii=False))
 return 0
if __name__=="__main__":sys.exit(main())
