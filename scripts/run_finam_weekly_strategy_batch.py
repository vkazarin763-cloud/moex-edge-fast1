#!/usr/bin/env python3
"""Read-only weekly research batch; market-data output is artifact-only."""
import json,os,time,csv,sys
from pathlib import Path
from collections import Counter
from datetime import datetime,timedelta,timezone
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import quote,urlencode
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experimental_portfolio.weekly_strategy_lab import validate_bars,compare,walk_forward_compare
from experimental_portfolio.deposit_benchmark import compare_to_deposit
from research_agent.finam_market_data import FinamMarketDataClient,create_access_token
BASE="https://api.finam.ru"; MIC="MISX"
UNIVERSE={"equity":["AFKS","AFLT","ALRS","BSPB","CBOM","CHMF","CNRU","DOMRF","ENPG","FLOT","GAZP","GMKN","HEAD","IRAO","LKOH","MAGN","MDMG","MOEX","MTSS","NLMK","NVTK","OZON","PHOR","PLZL","POSI","RAGR","RENI","ROSN","RTKM","RUAL","SBER","SBERP","SNGS","SNGSP","SVCB","T","TATN","TATNP","TRNFP","UGLD","VKCO","VTBR","X5","YDEX"],"fund":["AKME","AKMM","AMNR","AMNY","AMRE","AMRH","BCSD","DIVD","EQMX","GOLD","LQDT","SBCB","SBGB","SBMM","SBMX","SBRB","TBRU","TGLD","TMOS"]}
def req(url,token):
 try:
  with urlopen(Request(url,headers={"Authorization":"Bearer "+token,"Accept":"application/json"}),timeout=25) as x:return json.loads(x.read().decode())
 except HTTPError as e:raise RuntimeError("HTTP_"+str(e.code)) from None
 except (URLError,TimeoutError):raise RuntimeError("NETWORK") from None
def main():
 secret=os.getenv("FINAM_API_SECRET","").strip();account=os.getenv("FINAM_ACCOUNT_ID","").strip()
 if not secret or not account: print("BATCH=FAIL_CLOSED_SECRETS_MISSING");return 2
 token=create_access_token(secret);client=FinamMarketDataClient(token);end=datetime.now(timezone.utc);start=end-timedelta(days=365*5)
 screen_start=(end-timedelta(days=365)).date().isoformat()
 folder=Path("research_output");folder.mkdir(exist_ok=True);data={};report=[];counts=Counter()
 for kind,tickers in UNIVERSE.items():
  for ticker in tickers:
   symbol=ticker+"@"+MIC;item={"symbol":symbol,"asset_class":kind}
   # Finam bars schema does not declare a total-return/adjusted-price flag.
   # Do not assume dividends, distributions or splits are already reflected.
   item["return_basis"]="corporate_action_and_distribution_adjustment_unverified"
   try:
    q=urlencode({"account_id":account});enc=quote(symbol,safe="@")
    req(f"{BASE}/v1/assets/{enc}?{q}",token)
    p=req(f"{BASE}/v1/assets/{enc}/params?{q}",token);la=p.get("longable");la=la.get("value") if isinstance(la,dict) else la
    allowed=p.get("is_tradable") is True and la in ("AVAILABLE",1,"1");item["buy_permission"]=allowed
    if not allowed:item["status"]="BLOCKED_PERMISSION";counts[item["status"]]+=1
    else:
     fetched=client.fetch_bars(symbol,"TIME_FRAME_W",start,end,allow_preceding_weekly_bar=True)
     in_window=[b for b in fetched if start <= b.timestamp < end]
     bars=validate_bars([{"date":b.timestamp.date().isoformat(),"open":b.open,"high":b.high,"low":b.low,"close":b.close} for b in in_window])
     item.update({"valid_bars":len(bars),"from":bars[0]["date"] if bars else None,"to":bars[-1]["date"] if bars else None})
     if len(bars)>=200:
      data[symbol]=bars;item["status"]="QUALIFIED"
      metrics=compare(bars,evaluation_start=screen_start)
      for metric in metrics:
       if metric.get("status")=="OK":
        raw_screen=compare_to_deposit(metric,term="181_days_to_1_year")
        metric["raw_price_deposit_screen_status"]=raw_screen["status"]
        metric["deposit_screen"]={"status":"NOT_COMPARABLE","reason":"corporate_action_and_distribution_adjustment_unverified",
          "raw_price_cagr":metric.get("cagr"),"indicative_hurdle_rate":raw_screen.get("deposit_hurdle_rate"),
          "comparison_window":"trailing_approx_52_weeks","interpretation":"historical_price_only_not_total_return"}
        counts["DEPOSIT_NOT_COMPARABLE_ADJUSTMENT_UNVERIFIED"]+=1
       else:metric["deposit_screen"]={"status":"NOT_COMPARABLE","reason":metric.get("status")}
      item["metrics"]=metrics
      wf=walk_forward_compare(bars)
      item["walk_forward_metrics"]=wf
      item["walk_forward_folds"]=len({m["fold"] for m in wf})
      counts["WALK_FORWARD_ROWS"]+=len(wf)
      counts["QUALIFIED"]+=1
     else:item["status"]="INSUFFICIENT_HISTORY";counts[item["status"]]+=1
   except Exception as e:item["status"]="ERROR";item["error_code"]=str(e)[:160];counts["ERROR"]+=1
   report.append(item);time.sleep(.12)
 payload={"run_utc":datetime.now(timezone.utc).isoformat(),"policy":"permission check, 5y weekly history, >=200 validated bars; 13 strategies x 3 costs; sequential fixed-rule holdouts; price adjustment unverified; no trading",
  "return_basis":"corporate_action_and_distribution_adjustment_unverified",
  "deposit_benchmark":{"term":"181_days_to_1_year","comparison_window":"trailing_approx_52_weeks","status":"NOT_COMPARABLE_UNTIL_TOTAL_RETURN_ADJUSTMENT_VERIFIED","source":"Bank of Russia 2026-11-27 snapshot"},
  "walk_forward":{"warmup_bars":104,"fold_bars":52,"min_fold_bars":26,"method":"sequential fixed-rule holdouts; no parameter fitting"},
  "counts":dict(counts),"instruments":report,"validated_bars":data}
 (folder/"research.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2))
 fields=["symbol","class","strategy","cost","return","cagr","drawdown","volatility","sharpe","sharpe_status","exposure","turnover","bars","from","to","deposit_status","raw_price_screen_status","deposit_hurdle","walk_forward_folds"]
 with (folder/"metrics.csv").open("w",newline="",encoding="utf-8") as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
  for a in report:
   for m in a.get("metrics",[]):
    d=m.get("deposit_screen",{})
    w.writerow({"symbol":a["symbol"],"class":a["asset_class"],"strategy":m["strategy"],"cost":m["cost_stress"],"return":m.get("total_return"),"cagr":m.get("cagr"),"drawdown":m.get("max_drawdown"),"volatility":m.get("annualized_volatility"),"sharpe":m.get("sharpe_rf0"),"sharpe_status":m.get("sharpe_status"),"exposure":m.get("exposure_fraction"),"turnover":m.get("trades_or_rebalances"),"bars":m.get("evaluation_bars"),"from":m.get("period",{}).get("from"),"to":m.get("period",{}).get("to"),"deposit_status":d.get("status"),"raw_price_screen_status":m.get("raw_price_deposit_screen_status"),"deposit_hurdle":d.get("indicative_hurdle_rate"),"walk_forward_folds":a.get("walk_forward_folds")})
 wf_fields=["symbol","class","strategy","cost","fold","warmup_bars","test_from","test_to","cagr","total_return","max_drawdown","annualized_volatility","sharpe_rf0","sharpe_status","evaluation_bars","validation"]
 with (folder/"walk_forward.csv").open("w",newline="",encoding="utf-8") as f:
  w=csv.DictWriter(f,fieldnames=wf_fields);w.writeheader()
  for a in report:
   for m in a.get("walk_forward_metrics",[]):
    w.writerow({"symbol":a["symbol"],"class":a["asset_class"],**{k:(m.get("cost_stress") if k=="cost" else m.get(k)) for k in wf_fields if k not in ("symbol","class")}})
 print("WEEKLY_RESEARCH_BATCH=COMPLETE");print("SUMMARY="+json.dumps(dict(counts),sort_keys=True));print("SAFETY=READ_ONLY_NO_ORDERS_NO_COMMIT_MARKET_DATA");return 0
if __name__=="__main__":raise SystemExit(main())
