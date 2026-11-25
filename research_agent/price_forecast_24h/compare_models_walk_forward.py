"""Research-only expanding-window comparison of simple 24-H1-bar forecasts."""
from __future__ import annotations
import csv, gzip, json, math, statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("research_agent/price_forecast_24h")
DATA, REPORTS = ROOT / "data", ROOT / "reports"
HORIZON, MIN_TRAIN, FOLDS = 24, 120, 4


def load_archive(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def valid_weekday_bars(rows):
    out, seen = [], set()
    q = {"duplicates": 0, "invalid_ohlc": 0, "weekend_bars_excluded": 0}
    for r in sorted(rows, key=lambda x: x["timestamp"]):
        ts = datetime.fromisoformat(r["timestamp"])
        key = ts.isoformat()
        if key in seen:
            q["duplicates"] += 1
            continue
        seen.add(key)
        o, h, l, c = (float(r[k]) for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(v) and v > 0 for v in (o, h, l, c)) or l > min(o, c) or h < max(o, c) or l > h:
            q["invalid_ohlc"] += 1
            continue
        if ts.weekday() >= 5:
            q["weekend_bars_excluded"] += 1
            continue
        out.append((ts, c))
    return out, q


def ols_fit(xs, ys):
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x-mx)**2 for x in xs)
    beta = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / den if den else 0.0
    return my-beta*mx, beta


def make_folds(n):
    first = max(int(n * .50), MIN_TRAIN + HORIZON)
    width = (n-first)//FOLDS
    folds = []
    for k in range(FOLDS):
        start = first+k*width
        end = n if k == FOLDS-1 else first+(k+1)*width
        train_end = start-HORIZON
        if train_end >= MIN_TRAIN and end > start:
            folds.append((train_end, start, end))
    return folds


def score(actual, predicted):
    nonzero = [(y,p) for y,p in zip(actual,predicted) if abs(p)>1e-12]
    return {
        "mae_pct": statistics.fmean(abs(y-p) for y,p in zip(actual,predicted))*100,
        "rmse_pct": math.sqrt(statistics.fmean((y-p)**2 for y,p in zip(actual,predicted)))*100,
        "directional_accuracy_pct": statistics.fmean(1.0 if (p>0 and y>0) or (p<0 and y<0) else 0.0 for y,p in nonzero)*100 if nonzero else None,
        "nonzero_prediction_pct": sum(abs(p)>1e-12 for p in predicted)/len(predicted)*100,
    }


def evaluate_symbol(rows):
    bars, q = valid_weekday_bars(rows)
    samples = []
    for i in range(HORIZON, len(bars)-HORIZON):
        samples.append((bars[i][0].isoformat(),
                        math.log(bars[i][1]/bars[i-HORIZON][1]),
                        math.log(bars[i+HORIZON][1]/bars[i][1])))
    folds = make_folds(len(samples))
    if len(folds) < 3:
        return {"status":"INSUFFICIENT_DATA","bars_after_filter":len(bars),
                "samples_total":len(samples),"folds":len(folds),**q}
    names = ("zero_return","training_mean","momentum_1x","ols")
    actual_all, predictions = [], {n:[] for n in names}
    fold_report = []
    for no,(train_end,test_start,test_end) in enumerate(folds,1):
        train, test = samples[:train_end], samples[test_start:test_end]
        ys = [x[2] for x in train]
        alpha,beta = ols_fit([x[1] for x in train],ys)
        mean = statistics.fmean(ys)
        actual = [x[2] for x in test]
        preds = {
            "zero_return":[0.0]*len(test),
            "training_mean":[mean]*len(test),
            "momentum_1x":[x[1] for x in test],
            "ols":[alpha+beta*x[1] for x in test],
        }
        actual_all.extend(actual)
        for name in names: predictions[name].extend(preds[name])
        fold_report.append({"fold":no,"train_samples":len(train),"test_samples":len(test),
                            "test_start":test[0][0],"test_end":test[-1][0]})
    metrics = {n:score(actual_all,predictions[n]) for n in names}
    base = metrics["zero_return"]["mae_pct"]
    for n in names:
        metrics[n]["mae_improvement_vs_zero_pct"] = (base-metrics[n]["mae_pct"])/base*100 if base else None
    return {"status":"OK","bars_after_filter":len(bars),"samples_total":len(samples),
            "test_samples_total":len(actual_all),"folds":fold_report,"metrics":metrics,**q}


def main():
    archive = DATA/"H1_HISTORY.json.gz"
    if not archive.exists():
        raise SystemExit("Cumulative H1_HISTORY.json.gz not found; run the H1 collector first")
    payload = load_archive(archive)
    REPORTS.mkdir(parents=True,exist_ok=True)
    results = {t:evaluate_symbol(b["candles"]) for t,b in payload.get("symbols",{}).items()}
    valid = {t:v for t,v in results.items() if v.get("status")=="OK"}
    summary_models = {}
    for name in ("training_mean","momentum_1x","ols"):
        wins = [t for t,v in valid.items() if v["metrics"][name]["mae_pct"] < v["metrics"]["zero_return"]["mae_pct"]]
        improvements = [v["metrics"][name]["mae_improvement_vs_zero_pct"] for v in valid.values()]
        summary_models[name] = {
            "symbols_beating_zero_return":len(wins),"symbols_evaluated":len(valid),
            "median_mae_pct":statistics.median(v["metrics"][name]["mae_pct"] for v in valid.values()) if valid else None,
            "median_improvement_vs_zero_pct":statistics.median(improvements) if improvements else None,
            "winning_symbols":wins}
    summary = {
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "source":"Finam technical H1","horizon":"next 24 available weekday H1 bars",
        "universe_size":len(results),"symbols_evaluated":len(valid),
        "validation":"4 sequential expanding-window test folds over final 50% of samples; each training set ends 24 samples before its test block; test blocks do not overlap",
        "models":{"zero_return":"predict 0% return (price unchanged)",
                  "training_mean":"mean forward 24-bar return in training samples",
                  "momentum_1x":"next return equals previous 24-bar return",
                  "ols":"per-symbol OLS: forward return ~ intercept + beta * previous 24-bar return"},
        "summary_by_model":summary_models,
        "data_quality_totals":{k:sum(v.get(k,0) for v in results.values()) for k in ("weekend_bars_excluded","duplicates","invalid_ohlc")},
        "limitations":["Finam technical H1, not official MOEX session validation",
                       "weekday technical bars are a proxy; 24 bars are not guaranteed to equal 24 clock hours",
                       "no commissions, slippage, fills, exits, or profitability simulation",
                       "fixed 44-stock universe may contain survivorship/selection bias",
                       "research only; no trading or signal deployment"],
        "results":results}
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    jp=REPORTS/f"model-comparison-{stamp}.json"
    jp.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    cp=REPORTS/f"model-comparison-{stamp}.csv"
    fields=["ticker","status","samples_total","test_samples_total","folds","zero_mae_pct",
            "training_mean_mae_pct","momentum_1x_mae_pct","ols_mae_pct",
            "training_mean_improvement_pct","momentum_1x_improvement_pct","ols_improvement_pct",
            "weekend_bars_excluded","duplicates","invalid_ohlc"]
    with cp.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for t,v in results.items():
            m=v.get("metrics",{})
            w.writerow({"ticker":t,"status":v.get("status"),"samples_total":v.get("samples_total"),
                "test_samples_total":v.get("test_samples_total"),"folds":len(v.get("folds",[])),
                "zero_mae_pct":m.get("zero_return",{}).get("mae_pct"),
                "training_mean_mae_pct":m.get("training_mean",{}).get("mae_pct"),
                "momentum_1x_mae_pct":m.get("momentum_1x",{}).get("mae_pct"),
                "ols_mae_pct":m.get("ols",{}).get("mae_pct"),
                "training_mean_improvement_pct":m.get("training_mean",{}).get("mae_improvement_vs_zero_pct"),
                "momentum_1x_improvement_pct":m.get("momentum_1x",{}).get("mae_improvement_vs_zero_pct"),
                "ols_improvement_pct":m.get("ols",{}).get("mae_improvement_vs_zero_pct"),
                "weekend_bars_excluded":v.get("weekend_bars_excluded"),
                "duplicates":v.get("duplicates"),"invalid_ohlc":v.get("invalid_ohlc")})
    print(json.dumps({"status":"OK","symbols":len(results),"evaluated":len(valid),
                      "summary_by_model":summary_models,"json_report":str(jp),"csv_report":str(cp)},ensure_ascii=False))


if __name__ == "__main__":
    main()
