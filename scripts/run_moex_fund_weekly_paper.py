#!/usr/bin/env python3
"""Read-only Finam research + forward paper ledger for account-approved MOEX funds."""
from __future__ import annotations
import json,os,sys,time
from datetime import datetime,timezone,timedelta,date
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import quote,urlencode
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experimental_portfolio.moex_fund_weekly import run_weekly_backtest,current_weekly_targets,update_forward_ledger,MIN_HISTORY
from experimental_portfolio.agents import run_reviewers

BASE="https://api.finam.ru"
CANDIDATES=("AKME","AKMM","AMNR","AMNY","AMRE","AMRH","BCSD","DIVD","EQMX","GOLD","LQDT","SBCB","SBGB","SBMM","SBMX","SBRB","TBRU","TGLD","TMOS")
MIC="MISX"
def api(method,path,token=None,payload=None):
 h={"Accept":"application/json","Content-Type":"application/json"}
 if token:h["Authorization"]="Bearer "+token
 req=Request(BASE+path,headers=h,data=json.dumps(payload).encode() if payload is not None else None,method=method)
 try:
  with urlopen(req,timeout=25) as r:return json.loads(r.read().decode())
 except HTTPError as e:raise RuntimeError("Finam HTTP "+str(e.code)) from None
 except (URLError,TimeoutError) as e:raise RuntimeError("Finam network error "+type(e).__name__) from None
def val(v):
 if isinstance(v,dict):v=v.get("value")
 return float(v)
def parse_bars(symbol,bars):
 out={};bad=0
 for b in bars:
  try:
   stamp=b.get("timestamp")
   dt=datetime.fromisoformat(str(stamp).replace("Z","+00:00")).date()
   o,h,l,c=(val(b[k]) for k in ("open","high","low","close"))
   if not all(x>0 for x in (o,h,l,c)) or h<max(o,l,c) or l>min(o,h,c):raise ValueError("ohlc")
   v=b.get("volume");v=val(v) if v is not None else None
   out[dt.isoformat()]={"date":dt.isoformat(),"open":o,"high":h,"low":l,"close":c,"volume":v,"source":"Finam Trade API weekly","symbol":symbol}
  except Exception:bad+=1
 return [out[k] for k in sorted(out)],bad
def main():
 secret=os.getenv("FINAM_API_SECRET","").strip();account=os.getenv("FINAM_ACCOUNT_ID","").strip()
 outdir=Path("reports/experimental-portfolio/moex-funds");outdir.mkdir(parents=True,exist_ok=True)
 report={"generated_at_utc":datetime.now(timezone.utc).isoformat(),"universe":"Account-scoped MOEX funds, MIC MISX","paper_only":True,"orders_placed":False}
 if not secret or not account:
  report.update(status="FAIL_CLOSED_SECRETS_MISSING",eligible_symbols=[],history_errors={})
  (outdir/"latest.json").write_text(json.dumps(report,indent=2)+"\n")
  print("MOEX_FUND_WEEKLY=FAIL_CLOSED_SECRETS_MISSING");return 2
 try:
  token=api("POST","/v1/sessions",payload={"secret":secret}).get("token")
  if not token:raise RuntimeError("Finam session token missing")
  approved=[];perm_counts={}
  for ticker in CANDIDATES:
   sym=f"{ticker}@{MIC}"
   try:
    params=api("GET",f"/v1/assets/{quote(sym,safe='')}/params?{urlencode({'account_id':account})}",token)
    tradable=params.get("is_tradable") is True
    longable=params.get("longable");longable=longable.get("value") if isinstance(longable,dict) else longable
    key=str(longable or "MISSING");perm_counts[key]=perm_counts.get(key,0)+1
    if tradable and longable in ("AVAILABLE",1,"1"):approved.append(sym)
   except RuntimeError as e:
    key=str(e);perm_counts[key]=perm_counts.get(key,0)+1
   time.sleep(.15)
  end=datetime.now(timezone.utc);start=end-timedelta(days=365*5-15)
  q=urlencode({"timeframe":"TIME_FRAME_W","interval.start_time":start.isoformat(),"interval.end_time":end.isoformat()})
  hist={};errors={};badbars={}
  for sym in approved:
   try:
    data=api("GET",f"/v1/instruments/{quote(sym,safe='')}/bars?{q}",token)
    rows,bad=parse_bars(sym,data.get("bars",[]))
    if len(rows)>=MIN_HISTORY:hist[sym]=rows
    else:errors[sym]=f"insufficient_weekly_bars:{len(rows)}"
    if bad:badbars[sym]=bad
   except RuntimeError as e:errors[sym]=str(e)
   time.sleep(.15)
  research=run_weekly_backtest(hist)
  report.update(status=research["status"],account_permission_counts=perm_counts,eligible_symbols=approved,
    history_symbols=sorted(hist),history_errors=errors,invalid_bars=badbars,weekly_backtest=research,
    source="Finam Trade API account-scoped permissions + weekly bars",paper_only=True,orders_placed=False)
  ledger_path=Path("experimental_portfolio/moex_fund_paper_ledger.json")
  ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else None
  latest_date=max((rows[-1]["date"] for rows in hist.values() if rows),default=None)
  target=current_weekly_targets(hist)
  ledger=update_forward_ledger(hist,ledger,target)
  report["weekly_target_for_next_period"]=target
  report["forward_paper_ledger"]=ledger
  report["ai_review"]=run_reviewers(report)
  ledger_path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+"\n")
 except Exception as e:
  report.update(status="FAIL_CLOSED",error=f"{type(e).__name__}:{str(e)[:160]}",eligible_symbols=[],history_errors={})
  report["forward_paper_ledger"]={"status":"CASH_ONLY","nav_index":100.0,"cash_weight":1.0,"holdings":[],"paper_only":True,"orders_placed":False}
  print("MOEX_FUND_WEEKLY=FAIL_CLOSED "+report["error"])
 (outdir/"latest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
 (outdir/f"weekly-{date.today().isoformat()}.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
 state={"status":report.get("status"),"eligible_symbols":report.get("eligible_symbols",[]),"backtest_metrics":report.get("weekly_backtest",{}).get("metrics"),"paper_nav_index":report.get("forward_paper_ledger",{}).get("nav_index"),"cash_weight":report.get("forward_paper_ledger",{}).get("cash_weight"),"holdings":report.get("forward_paper_ledger",{}).get("holdings",[]),"paper_only":True,"orders_placed":False}
 Path("experimental_portfolio/moex_fund_state.json").write_text(json.dumps(state,indent=2)+"\n")
 print("MOEX_FUND_WEEKLY="+str(report.get("status"))+" approved="+str(len(report.get("eligible_symbols",[])))+" history="+str(len(report.get("history_symbols",[])))+" backtest="+str(report.get("weekly_backtest",{}).get("metrics"))+" paper_cash="+str(report.get("forward_paper_ledger",{}).get("cash_weight"))+" orders=false")
 return 0
if __name__=="__main__":sys.exit(main())
