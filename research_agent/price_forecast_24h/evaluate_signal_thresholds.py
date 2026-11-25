"""Research-only fixed-threshold signal selection test on out-of-sample folds."""
# Fixed thresholds are specified before test-fold evaluation.
from __future__ import annotations
import csv,gzip,json,math,statistics
from datetime import datetime,timezone
from pathlib import Path
from research_agent.price_forecast_24h.evaluate_trend_candle_features import (
    build_samples,folds_for,fit_ridge,predict
)

ROOT=Path("research_agent/price_forecast_24h")
DATA,REPORTS=ROOT/"data",ROOT/"reports"
THRESHOLDS=(0.005,0.01,0.015,0.02)


def summarize(trades):
    if not trades:
        return {"signals":0,"coverage_pct":0.0,"win_rate_pct":None,
                "mean_signed_return_pct":None,"median_signed_return_pct":None,
                "positive_folds":0,"folds_with_signals":0}
    vals=[x["signed_return"] for x in trades]
    folds={}
    for x in trades: folds.setdefault(x["fold"],[]).append(x["signed_return"])
    return {
        "signals":len(vals),
        "coverage_pct":None,
        "win_rate_pct":sum(v>0 for v in vals)/len(vals)*100,
        "mean_signed_return_pct":statistics.fmean(vals)*100,
        "median_signed_return_pct":statistics.median(vals)*100,
        "positive_folds":sum(statistics.fmean(v)>0 for v in folds.values()),
        "folds_with_signals":len(folds)
    }


def evaluate(rows):
    samples,q,bars=build_samples(rows)
    folds=folds_for(len(samples))
    if len(folds)<3:
        return {"status":"INSUFFICIENT_DATA","bars_after_filter":bars,
                "samples_total":len(samples),"folds":len(folds),**q}
    names=("momentum_1x","trend_candle_ridge")
    accum={name:{thr:[] for thr in THRESHOLDS} for name in names}
    n_test=0; fold_meta=[]
    for fold_no,(train_end,test_start,test_end) in enumerate(folds,1):
        train=samples[:train_end]; test=samples[test_start:test_end]
        model=fit_ridge(train)
        fold_meta.append({"fold":fold_no,"train_samples":len(train),
            "test_samples":len(test),"test_start":test[0]["timestamp"],
            "test_end":test[-1]["timestamp"]})
        n_test+=len(test)
        for s in test:
            scores={"momentum_1x":s["momentum"],
                    "trend_candle_ridge":predict(model,s["x"])}
            for name,score in scores.items():
                for threshold in THRESHOLDS:
                    if abs(score)>=threshold:
                        signed=(1 if score>0 else -1)*s["y"]
                        accum[name][threshold].append({
                            "fold":fold_no,"signed_return":signed,
                            "raw_return":s["y"],"score":score})
    out={}
    for name in names:
        out[name]={}
        for threshold,trades in accum[name].items():
            s=summarize(trades)
            s["coverage_pct"]=len(trades)/n_test*100 if n_test else 0
            s["threshold_pct"]=threshold*100
            out[name][str(threshold)] = s
    return {"status":"OK","bars_after_filter":bars,"samples_total":len(samples),
            "test_samples_total":n_test,"folds":fold_meta,"threshold_results":out,**q}


def main():
    archive=DATA/"H1_HISTORY.json.gz"
    if not archive.exists(): raise SystemExit("Cumulative H1_HISTORY.json.gz not found")
    payload=json.loads(gzip.open(archive,"rt",encoding="utf-8").read())
    REPORTS.mkdir(parents=True,exist_ok=True)
    results={t:evaluate(v["candles"]) for t,v in payload.get("symbols",{}).items()}
    valid={t:v for t,v in results.items() if v.get("status")=="OK"}
    aggregate={}
    for name in ("momentum_1x","trend_candle_ridge"):
        aggregate[name]={}
        for threshold in THRESHOLDS:
            key=str(threshold); rows=[]
            total_signals=total_test=0; wins=0; signed_sum=0.0
            ticker_positive=0; ticker_count=0; positive_folds=fold_count=0
            for ticker,v in valid.items():
                s=v["threshold_results"][name][key]
                total_test+=v["test_samples_total"]
                total_signals+=s["signals"]
                if s["signals"]:
                    ticker_count+=1
                    ticker_positive+=s["mean_signed_return_pct"]>0
                    wins+=s["win_rate_pct"]*s["signals"]/100
                    signed_sum+=s["mean_signed_return_pct"]*s["signals"]/100
                    positive_folds+=s["positive_folds"]; fold_count+=s["folds_with_signals"]
            aggregate[name][key]={
                "threshold_pct":threshold*100,
                "signals":total_signals,
                "coverage_pct":total_signals/total_test*100 if total_test else 0,
                "weighted_win_rate_pct":wins/total_signals*100 if total_signals else None,
                "weighted_mean_signed_return_pct":signed_sum/total_signals if total_signals else None,
                "tickers_with_signals":ticker_count,
                "tickers_with_positive_mean_return":ticker_positive,
                "positive_folds":positive_folds,"folds_with_signals":fold_count}
    report={"generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "source":"Finam technical H1","horizon":"next 24 available weekday H1 bars",
        "universe_size":len(results),"symbols_evaluated":len(valid),
        "validation":"4 sequential expanding-window out-of-sample folds; 24-sample embargo; thresholds fixed in advance",
        "rule":"Take LONG when model score >= threshold; SHORT when score <= -threshold; otherwise no trade. Signed return is direction * realized forward log return.",
        "thresholds_pct":[x*100 for x in THRESHOLDS],
        "models":{"momentum_1x":"previous 24-bar return used as direction score",
            "trend_candle_ridge":"ridge score using trend, volatility and candle features"},
        "aggregate":aggregate,"results":results,
        "limitations":["gross returns only; no commissions, slippage, spread or execution simulation",
            "Finam technical H1, not official MOEX session validation",
            "24 weekday bars are not guaranteed to equal 24 clock hours",
            "thresholds are exploratory fixed levels, not optimized or production-ready",
            "research only; no signal or trading deployment"]}
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    jp=REPORTS/f"threshold-signal-test-{stamp}.json"
    jp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    cp=REPORTS/f"threshold-signal-test-{stamp}.csv"
    fields=["ticker","model","threshold_pct","signals","coverage_pct","win_rate_pct",
        "mean_signed_return_pct","median_signed_return_pct","positive_folds","folds_with_signals"]
    with cp.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for ticker,v in results.items():
            if v.get("status")!="OK": continue
            for model,levels in v["threshold_results"].items():
                for s in levels.values():
                    w.writerow({"ticker":ticker,"model":model,**s})
    print(json.dumps({"status":"OK","symbols":len(results),"evaluated":len(valid),
        "aggregate":aggregate,"json_report":str(jp),"csv_report":str(cp)},ensure_ascii=False))


if __name__=="__main__":main()
