#!/usr/bin/env python3
"""Read-only validation of weekly Finam bars for approved MOEX funds."""
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
 if not secret:print("WEEKLY_PROBE=FAIL_MISSING_SECRET");return 2
 token=req("POST","/v1/sessions",body={"secret":secret}).get("token")
 if not token:print("WEEKLY_PROBE=FAIL_TOKEN");return 2
 end=datetime.now(timezone.utc);start=end-timedelta(days=365*5-20)
 q=urlencode({"timeframe":"TIME_FRAME_W","interval.start_time":start.isoformat(),"interval.end_time":end.isoformat()})
 details=[];ok=bad=0
 for t in CANDIDATES:
  try:
   data=req("GET",f"/v1/instruments/{quote(t+'@'+MIC,safe='')}/bars?{q}",token)
   bars=data.get("bars",[]);valid=0;dates=[]
   for b in bars:
    try:
     vals=[float(b[k].get("value") if isinstance(b[k],dict) else b[k]) for k in ("open","high","low","close")]
     if not all(math.isfinite(x) and x>0 for x in vals):continue
     o,h,l,c=vals
     if h<max(o,l,c) or l>min(o,h,c):continue
     valid+=1;dates.append(str(b.get("timestamp") or ""))
    except Exception:continue
   ok+=1;details.append({"ticker":t,"bars":len(bars),"valid":valid,"first":dates[0] if dates else None,"last":dates[-1] if dates else None})
  except RuntimeError as e:bad+=1;details.append({"ticker":t,"error":str(e)})
 print("WEEKLY_PROBE=COMPLETE candidates="+str(len(CANDIDATES))+" success="+str(ok)+" errors="+str(bad))
 print("WEEKLY_SUMMARY="+json.dumps(details,ensure_ascii=False))
 return 0
if __name__=="__main__":sys.exit(main())
