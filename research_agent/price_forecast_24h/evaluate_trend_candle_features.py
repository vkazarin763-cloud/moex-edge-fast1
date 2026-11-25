"""Leakage-aware feature experiment: trend, realized volatility and candle geometry."""
from __future__ import annotations
import csv, gzip, json, math, statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path("research_agent/price_forecast_24h")
DATA,REPORTS=ROOT/"data",ROOT/"reports"
HORIZON=24
MIN_TRAIN=120
FOLDS=4
RIDGE_ALPHA=0.10


def load_archive(path):
    with gzip.open(path,"rt",encoding="utf-8") as f:
        return json.load(f)


def clean_bars(rows):
    out=[]; seen=set()
    q={"duplicates":0,"invalid_ohlc":0,"weekend_bars_excluded":0}
    for r in sorted(rows,key=lambda x:x["timestamp"]):
        ts=datetime.fromisoformat(r["timestamp"])
        key=ts.isoformat()
        if key in seen:
            q["duplicates"]+=1; continue
        seen.add(key)
        o,h,l,c=(float(r[k]) for k in ("open","high","low","close"))
        if (not all(math.isfinite(v) and v>0 for v in (o,h,l,c))
            or l>min(o,c) or h<max(o,c) or l>h):
            q["invalid_ohlc"]+=1; continue
        if ts.weekday()>=5:
            q["weekend_bars_excluded"]+=1; continue
        out.append({"timestamp":ts.isoformat(),"open":o,"high":h,"low":l,"close":c})
    return out,q


def rolling_std(values,end,window):
    seq=values[end-window+1:end+1]
    if len(seq)!=window: return None
    return statistics.pstdev(seq)


def build_samples(rows):
    bars,q=clean_bars(rows)
    closes=[b["close"] for b in bars]
    logrets=[None]+[math.log(closes[i]/closes[i-1]) for i in range(1,len(closes))]
    ema12=[]; ema48=[]
    for i,c in enumerate(closes):
        ema12.append(c if i==0 else (2/13)*c+(1-2/13)*ema12[-1])
        ema48.append(c if i==0 else (2/49)*c+(1-2/49)*ema48[-1])
    samples=[]
    for i in range(72,len(bars)-HORIZON):
        vol24=rolling_std(logrets,i,24)
        vol72=rolling_std(logrets,i,72)
        if vol24 is None or vol72 is None: continue
        b=bars[i]
        span=b["high"]-b["low"]
        features=[
            math.log(closes[i]/closes[i-6]),
            math.log(closes[i]/closes[i-24]),
            math.log(closes[i]/closes[i-72]),
            math.log(ema12[i]/ema48[i]),
            vol24,vol72,
            math.log(b["close"]/b["open"]),
            span/b["close"],
            ((b["close"]-b["low"])/span*2-1) if span>0 else 0.0,
        ]
        target=math.log(closes[i+HORIZON]/closes[i])
        samples.append({"timestamp":b["timestamp"],"x":features,"y":target,
                        "momentum":features[1]})
    return samples,q,len(bars)


def folds_for(n):
    first=max(int(n*.50),MIN_TRAIN+HORIZON)
    width=(n-first)//FOLDS
    folds=[]
    for k in range(FOLDS):
        start=first+k*width
        end=n if k==FOLDS-1 else first+(k+1)*width
        train_end=start-HORIZON
        if train_end>=MIN_TRAIN and end>start:
            folds.append((train_end,start,end))
    return folds


def solve(a,b):
    n=len(b)
    m=[list(map(float,a[i]))+[float(b[i])] for i in range(n)]
    for col in range(n):
        pivot=max(range(col,n),key=lambda r:abs(m[r][col]))
        if abs(m[pivot][col])<1e-12:
            raise ArithmeticError("singular ridge system")
        m[col],m[pivot]=m[pivot],m[col]
        scale=m[col][col]
        for j in range(col,n+1): m[col][j]/=scale
        for r in range(n):
            if r==col: continue
            factor=m[r][col]
            if factor:
                for j in range(col,n+1): m[r][j]-=factor*m[col][j]
    return [m[i][n] for i in range(n)]


def fit_ridge(train,alpha=RIDGE_ALPHA):
    p=len(train[0]["x"])
    means=[statistics.fmean(s["x"][j] for s in train) for j in range(p)]
    scales=[]
    for j in range(p):
        sd=statistics.pstdev(s["x"][j] for s in train)
        scales.append(sd if sd>1e-12 else 1.0)
    ys=[s["y"] for s in train]
    ymean=statistics.fmean(ys)
    xz=[[(s["x"][j]-means[j])/scales[j] for j in range(p)] for s in train]
    xtx=[[sum(row[i]*row[j] for row in xz)/len(xz)+(alpha if i==j else 0.0)
          for j in range(p)] for i in range(p)]
    xty=[sum(xz[k][j]*(ys[k]-ymean) for k in range(len(xz)))/len(xz) for j in range(p)]
    beta=solve(xtx,xty)
    return means,scales,ymean,beta


def predict(model,x):
    means,scales,ymean,beta=model
    return ymean+sum(beta[j]*(x[j]-means[j])/scales[j] for j in range(len(x)))


def metrics(actual,pred):
    mae=statistics.fmean(abs(y-p) for y,p in zip(actual,pred))
    rmse=math.sqrt(statistics.fmean((y-p)**2 for y,p in zip(actual,pred)))
    used=[(y,p) for y,p in zip(actual,pred) if abs(p)>1e-12]
    return {"mae_pct":mae*100,"rmse_pct":rmse*100,
            "directional_accuracy_pct":statistics.fmean(1 if y*p>0 else 0 for y,p in used)*100 if used else None,
            "nonzero_prediction_pct":len(used)/len(actual)*100 if actual else 0}


def evaluate(rows):
    samples,q,bars_count=build_samples(rows)
    folds=folds_for(len(samples))
    if len(folds)<3:
        return {"status":"INSUFFICIENT_DATA","bars_after_filter":bars_count,
                "samples_total":len(samples),"folds":len(folds),**q}
    names=("zero_return","training_mean","momentum_1x","trend_candle_ridge")
    actual_all=[]; preds={n:[] for n in names}; fold_meta=[]
    for no,(train_end,test_start,test_end) in enumerate(folds,1):
        train=samples[:train_end]
        test=samples[test_start:test_end]
        model=fit_ridge(train)
        y=[s["y"] for s in test]
        p={
            "zero_return":[0.0]*len(test),
            "training_mean":[statistics.fmean(s["y"] for s in train)]*len(test),
            "momentum_1x":[s["momentum"] for s in test],
            "trend_candle_ridge":[predict(model,s["x"]) for s in test],
        }
        actual_all.extend(y)
        for n in names: preds[n].extend(p[n])
        fold_meta.append({"fold":no,"train_samples":len(train),"test_samples":len(test),
                          "test_start":test[0]["timestamp"],"test_end":test[-1]["timestamp"]})
    result={n:metrics(actual_all,preds[n]) for n in names}
    base=result["zero_return"]["mae_pct"]
    for n in names:
        result[n]["mae_improvement_vs_zero_pct"]=(base-result[n]["mae_pct"])/base*100 if base else None
    return {"status":"OK","bars_after_filter":bars_count,"samples_total":len(samples),
            "test_samples_total":len(actual_all),"folds":fold_meta,"metrics":result,**q}


def main():
    archive=DATA/"H1_HISTORY.json.gz"
    if not archive.exists(): raise SystemExit("Cumulative H1_HISTORY.json.gz not found")
    payload=load_archive(archive)
    REPORTS.mkdir(parents=True,exist_ok=True)
    results={t:evaluate(v["candles"]) for t,v in payload.get("symbols",{}).items()}
    valid={t:v for t,v in results.items() if v.get("status")=="OK"}
    summary={}
    for name in ("training_mean","momentum_1x","trend_candle_ridge"):
        wins=[t for t,v in valid.items() if v["metrics"][name]["mae_pct"]<v["metrics"]["zero_return"]["mae_pct"]]
        improvements=[v["metrics"][name]["mae_improvement_vs_zero_pct"] for v in valid.values()]
        summary[name]={"symbols_beating_zero_return":len(wins),"symbols_evaluated":len(valid),
            "median_mae_pct":statistics.median(v["metrics"][name]["mae_pct"] for v in valid.values()) if valid else None,
            "median_improvement_vs_zero_pct":statistics.median(improvements) if improvements else None,
            "winning_symbols":wins}
    report={"generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "source":"Finam technical H1","horizon":"next 24 available weekday H1 bars",
        "universe_size":len(results),"symbols_evaluated":len(valid),
        "validation":"4 sequential expanding-window folds over final 50% of samples; 24-sample embargo between train and test",
        "features":["6-bar log return","24-bar log return","72-bar log return",
            "EMA12/EMA48 log spread","24-bar realized volatility","72-bar realized volatility",
            "current candle log body","current candle high-low range / close",
            "current candle close location within range"],
        "model":"per-symbol ridge regression; feature standardization fitted on training fold only; alpha=0.10 fixed before evaluation",
        "models":{"zero_return":"predict zero return","training_mean":"training-fold mean forward return",
            "momentum_1x":"previous 24-bar return repeated","trend_candle_ridge":"ridge using trend, volatility and candle geometry"},
        "summary_by_model":summary,
        "data_quality_totals":{k:sum(v.get(k,0) for v in results.values()) for k in ("weekend_bars_excluded","duplicates","invalid_ohlc")},
        "limitations":["Finam technical H1, not official MOEX session validation",
            "24 weekday technical H1 bars are not guaranteed to equal 24 clock hours",
            "no costs, fills, exits or profitability simulation","fixed universe may have survivorship bias",
            "research only; no signals or trading deployment"],
        "results":results}
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    jp=REPORTS/f"feature-comparison-{stamp}.json"
    jp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    cp=REPORTS/f"feature-comparison-{stamp}.csv"
    fields=["ticker","status","samples_total","test_samples_total","folds","zero_mae_pct",
        "training_mean_mae_pct","momentum_1x_mae_pct","trend_candle_ridge_mae_pct",
        "trend_candle_ridge_improvement_pct","weekend_bars_excluded","duplicates","invalid_ohlc"]
    with cp.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for t,v in results.items():
            m=v.get("metrics",{})
            w.writerow({"ticker":t,"status":v.get("status"),"samples_total":v.get("samples_total"),
                "test_samples_total":v.get("test_samples_total"),"folds":len(v.get("folds",[])),
                "zero_mae_pct":m.get("zero_return",{}).get("mae_pct"),
                "training_mean_mae_pct":m.get("training_mean",{}).get("mae_pct"),
                "momentum_1x_mae_pct":m.get("momentum_1x",{}).get("mae_pct"),
                "trend_candle_ridge_mae_pct":m.get("trend_candle_ridge",{}).get("mae_pct"),
                "trend_candle_ridge_improvement_pct":m.get("trend_candle_ridge",{}).get("mae_improvement_vs_zero_pct"),
                "weekend_bars_excluded":v.get("weekend_bars_excluded"),
                "duplicates":v.get("duplicates"),"invalid_ohlc":v.get("invalid_ohlc")})
    print(json.dumps({"status":"OK","symbols":len(results),"evaluated":len(valid),
        "summary_by_model":summary,"json_report":str(jp),"csv_report":str(cp)},ensure_ascii=False))


if __name__=="__main__": main()
