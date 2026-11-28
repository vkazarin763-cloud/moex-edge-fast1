from datetime import date,timedelta
from experimental_portfolio.moex_fund_weekly import run_weekly_backtest,current_weekly_targets

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
