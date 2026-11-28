from datetime import date,timedelta
from experimental_portfolio.moex_fund_weekly import run_weekly_backtest,current_weekly_targets,update_forward_ledger,normalized_reviewer_context

def make_hist(n=240):
    hist={}
    start=date(2022,1,3)
    for j,s in enumerate(("A@MISX","B@MISX","C@MISX","D@MISX","TMOS@MISX")):
        rows=[]
        for i in range(n):
            d=(start+timedelta(days=7*i)).isoformat()
            # deterministic positive drift with small smooth variation
            close=100*(1+0.0015*(i+j))*(1+0.01*((i%11)-5))
            rows.append({"date":d,"open":close*.998,"high":close*1.01,"low":close*.99,"close":close})
        hist[s]=rows
    return hist

def test_weekly_backtest_has_valid_metrics_and_safe_targets():
    hist=make_hist()
    report=run_weekly_backtest(hist)
    assert report["status"]=="READY"
    assert report["metrics"]["observations"]>0
    assert report["metrics"]["ending_nav"]>0
    assert report["metrics"]["max_drawdown"]<=0
    targets=current_weekly_targets(hist)
    assert len(targets)<=4
    if targets:assert abs(sum(x["weight"] for x in targets)-1)<1e-5

def test_assets_shorter_than_minimum_are_excluded():
    hist=make_hist()
    hist["SHORT@MISX"]=hist["A@MISX"][:120]
    report=run_weekly_backtest(hist)
    assert "SHORT@MISX" in report["excluded_short_history"]
    assert "SHORT@MISX" not in report["eligible_symbols"]

def test_insufficient_universe_stays_no_strategy():
    report=run_weekly_backtest({"A@MISX":make_hist()["A@MISX"]})
    assert report["status"]=="INSUFFICIENT_HISTORY"
    assert report["metrics"] is None

def test_forward_ledger_starts_cash_and_does_not_replay():
    hist=make_hist()
    targets=current_weekly_targets(hist)
    ledger=update_forward_ledger(hist,None,targets)
    assert ledger["nav_index"]==100
    assert ledger["cash_weight"]==1
    assert ledger["holdings"]==[]
    assert ledger["orders_placed"] is False
    unchanged=update_forward_ledger(hist,ledger,targets)
    assert unchanged["nav_index"]==100
    assert unchanged["last_processed_week"]==ledger["last_processed_week"]

def test_forward_ledger_advances_only_on_new_week():
    hist=make_hist()
    targets=current_weekly_targets(hist)
    ledger=update_forward_ledger(hist,None,targets)
    for symbol,rows in hist.items():
        last=rows[-1]
        newdate=(date.fromisoformat(last["date"])+timedelta(days=7)).isoformat()
        close=last["close"]*1.01
        rows.append({"date":newdate,"open":last["close"],"high":close*1.01,"low":last["close"]*.99,"close":close})
    updated=update_forward_ledger(hist,ledger,targets)
    assert updated["status"]=="FORWARD_PAPER"
    assert updated["last_processed_week"]>ledger["last_processed_week"]
    assert updated["nav_index"]>100
    assert updated["orders_placed"] is False

def test_review_context_includes_weekly_metrics_and_ledger():
    report={"weekly_backtest":{"period":{"start":"2023-01-01","end":"2025-01-01"},
      "metrics":{"total_return":0.2,"max_drawdown":-0.1},
      "benchmark_buy_hold":{"symbol":"TMOS@MISX","total_return":0.05},
      "strategy":{"trend_filter":"40w"}},
      "forward_paper_ledger":{"nav_index":100,"cash_weight":1,"holdings":[]},
      "history_errors":{"X@MISX":"missing"}}
    ctx=normalized_reviewer_context(report)
    assert ctx["performance"]["total_return"]==0.2
    assert ctx["historical_backtest"]["period"]["from"]=="2023-01-01"
    assert ctx["benchmark_buy_and_hold"]["symbol"]=="TMOS@MISX"
    assert ctx["paper_portfolio"]["nav_index"]==100
    assert ctx["data_errors"]["X@MISX"]=="missing"
