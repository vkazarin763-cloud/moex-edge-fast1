#!/usr/bin/env python3
"""Daily global ETF paper portfolio run; no broker or order access."""
from __future__ import annotations
import argparse,json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from experimental_portfolio.agents import run_reviewers
from experimental_portfolio.engine import SOURCE,UNIVERSE,build_report,download_universe
from experimental_portfolio.paper import update_paper_ledger
from experimental_portfolio.eligibility import load_finam_allowlist

def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--years",type=int,default=3)
    parser.add_argument("--output-dir",default="reports/experimental-portfolio")
    args=parser.parse_args()
    if not 1<=args.years<=10: raise SystemExit("--years must be between 1 and 10")
    end=datetime.now(timezone.utc).date()
    start=end-timedelta(days=365*args.years+30)
    allowlist=load_finam_allowlist()
    approved=set(allowlist["allowed_symbols"])
    history,errors=download_universe(start,end,approved)
    history={s:r for s,r in history.items() if s in approved}
    errors={**errors,**{s:"blocked_by_finam_account_allowlist" for s in [x["symbol"] for x in UNIVERSE if x["symbol"] not in approved]}}
    report=build_report(history,errors,allowed_symbols=approved)
    report["finam_account_eligibility"]=allowlist
    report["eligibility_policy"]="Fail closed: only account-confirmed Finam BUY_ALLOWED instruments may be selected. No confirmed symbols means cash only."
    report["universe_requested"]=[x["symbol"] for x in UNIVERSE]
    report["run_mode"]="AUTONOMOUS_RESEARCH_AND_FORWARD_PAPER_ONLY"
    report["data_source"]=SOURCE

    # Keep historical replay and forward paper ledger explicitly separate.
    report["historical_backtest"]={
        "period":report.get("period"),
        "performance":report.get("performance"),
        "benchmark_spy_buy_and_hold":report.get("benchmark_spy_buy_and_hold"),
        "latest_model_weights":report.get("holdings",[]),
        "notice":"Historical simulation only. It is not the prospective paper portfolio and does not seed paper holdings.",
    }
    ledger_path=Path("experimental_portfolio/paper_ledger.json")
    existing=None
    if ledger_path.exists():
        existing=json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger=update_paper_ledger(history,existing,allowed_symbols=approved)
    if not approved and existing is None:
        ledger={"version":1,"status":"WAITING_FOR_FINAM_ACCOUNT_ALLOWLIST","start_date":end.isoformat(),"last_processed_date":end.isoformat(),"updated_at_utc":datetime.now(timezone.utc).isoformat(),"nav_index":100.0,"high_watermark":100.0,"max_drawdown":0.0,"last_daily_return":0.0,"holdings":[],"cash_weight":1.0,"last_rebalance_month":None,"rebalance_count":0,"cumulative_turnover":0.0,"paper_only":True,"orders_placed":False,"note":"Fail-closed: no account-verified Finam buyable assets in allowlist; portfolio stays 100% cash."}
    ledger_path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    report["paper_portfolio"]=ledger
    report["holdings"]=ledger.get("holdings",[])
    report["cash_weight"]=ledger.get("cash_weight")
    report["ai_review"]=run_reviewers(report)

    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    rendered=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    (out/"latest.json").write_text(rendered,encoding="utf-8")
    (out/f"portfolio-{end.isoformat()}.json").write_text(rendered,encoding="utf-8")
    state={
      "updated_at_utc":report.get("generated_at_utc"),"data_status":report.get("status"),
      "paper_status":ledger.get("status"),"portfolio_index":ledger.get("nav_index"),
      "paper_holdings":ledger.get("holdings",[]),"cash_weight":ledger.get("cash_weight"),
      "last_processed_date":ledger.get("last_processed_date"),
      "historical_backtest_index":report.get("performance",{}).get("ending_nav_index"),
      "ai_review_status":report.get("ai_review",{}).get("status"),
      "ai_agents_completed":report.get("ai_review",{}).get("agents_completed",0),
      "safety":report.get("safety"),
    }
    Path("experimental_portfolio/state.json").write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
      "data_status":report.get("status"),"assets_requested":len(UNIVERSE),
      "assets_with_history":len(history),"data_errors":len(errors),
      "historical_backtest_index":report.get("performance",{}).get("ending_nav_index"),
      "paper_status":ledger.get("status"),"paper_nav_index":ledger.get("nav_index"),
      "paper_holdings":len(ledger.get("holdings",[])),"cash_weight":ledger.get("cash_weight"),
      "finam_allowed_symbols":allowlist["allowed_symbols"],"eligibility_blocked":len(allowlist["blocked_symbols"]),
      "ai_review":report["ai_review"]["status"],"ai_agents_completed":report["ai_review"].get("agents_completed",0),
      "paper_only":True,"orders_placed":False,
    },ensure_ascii=False))
    return 0
if __name__=="__main__": raise SystemExit(main())
