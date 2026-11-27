#!/usr/bin/env python3
"""Daily global ETF paper portfolio run; no broker or order access."""
from __future__ import annotations
import argparse,json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from experimental_portfolio.agents import run_reviewers
from experimental_portfolio.engine import SOURCE,UNIVERSE,build_report,download_universe

def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--years",type=int,default=3)
    parser.add_argument("--output-dir",default="reports/experimental-portfolio")
    args=parser.parse_args()
    if not 1<=args.years<=10: raise SystemExit("--years must be between 1 and 10")
    end=datetime.now(timezone.utc).date()
    start=end-timedelta(days=365*args.years+30)
    history,errors=download_universe(start,end)
    report=build_report(history,errors)
    report["universe_requested"]=[x["symbol"] for x in UNIVERSE]
    report["ai_review"]=run_reviewers(report)
    report["run_mode"]="AUTONOMOUS_RESEARCH_PAPER_ONLY"
    report["data_source"]=SOURCE
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    rendered=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    (out/"latest.json").write_text(rendered,encoding="utf-8")
    (out/f"portfolio-{end.isoformat()}.json").write_text(rendered,encoding="utf-8")
    state={"updated_at_utc":report.get("generated_at_utc"),"status":report.get("status"),
      "portfolio_index":report.get("performance",{}).get("ending_nav_index"),
      "holdings":report.get("holdings",[]),"cash_weight":report.get("cash_weight"),
      "ai_review_status":report.get("ai_review",{}).get("status"),"safety":report.get("safety")}
    Path("experimental_portfolio/state.json").write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":report.get("status"),"assets_requested":len(UNIVERSE),
      "assets_with_history":len(history),"data_errors":len(errors),
      "portfolio_index":report.get("performance",{}).get("ending_nav_index"),
      "holdings":len(report.get("holdings",[])),"ai_review":report["ai_review"]["status"],
      "ai_agents_completed":report["ai_review"].get("agents_completed",0),
      "paper_only":report.get("safety",{}).get("paper_only"),"orders_placed":False},ensure_ascii=False))
    return 0
if __name__=="__main__": raise SystemExit(main())
