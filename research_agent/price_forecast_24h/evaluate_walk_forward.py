"""Leakage-aware, per-symbol 24-H1-bar return forecast experiment.

Uses Finam technical H1 candles, removes weekends, retains weekday observations
without claiming official MOEX session/calendar validation. No trading.
"""
from __future__ import annotations
import csv, gzip, json, math, statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("research_agent/price_forecast_24h")
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
HORIZON = 24
TRAIN_FRACTION = 0.70


def load_archive(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def valid_weekday_bars(rows):
    out = []
    seen = set()
    invalid = duplicates = weekends = 0
    for r in sorted(rows, key=lambda x: x["timestamp"]):
        ts = datetime.fromisoformat(r["timestamp"])
        key = ts.isoformat()
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        o, h, l, c = (float(r[k]) for k in ("open", "high", "low", "close"))
        if min(o, h, l, c) <= 0 or l > min(o, c) or h < max(o, c) or l > h:
            invalid += 1
            continue
        # Finam timestamps are UTC. Weekends are known technical-feed bars,
        # not MOEX equity sessions; discard them. Keep weekday bars as proxy.
        if ts.weekday() >= 5:
            weekends += 1
            continue
        out.append((ts, c))
    return out, {"duplicates": duplicates, "invalid_ohlc": invalid,
                 "weekend_bars_excluded": weekends}


def ols_fit(xs, ys):
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x-mx)**2 for x in xs)
    beta = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / den if den else 0.0
    return my - beta*mx, beta


def evaluate_symbol(rows):
    bars, quality = valid_weekday_bars(rows)
    n = len(bars)
    # One sample: past 24 available weekday bars -> next 24 available bars.
    samples = []
    for i in range(HORIZON, n-HORIZON):
        past = math.log(bars[i][1] / bars[i-HORIZON][1])
        future = math.log(bars[i+HORIZON][1] / bars[i][1])
        samples.append((bars[i][0].isoformat(), past, future))
    if len(samples) < 120:
        return {"status":"INSUFFICIENT_DATA","bars_after_filter":n,
                "samples":len(samples), **quality}
    split = int(len(samples)*TRAIN_FRACTION)
    train = samples[:split]
    # Embargo one full forecast horizon to prevent overlapping labels.
    test = samples[min(len(samples), split+HORIZON):]
    if len(train) < 60 or len(test) < 24:
        return {"status":"INSUFFICIENT_DATA","bars_after_filter":n,
                "samples":len(samples), **quality}
    alpha, beta = ols_fit([x[1] for x in train], [x[2] for x in train])
    actual = [x[2] for x in test]
    pred = [alpha + beta*x[1] for x in test]
    baseline = [0.0]*len(actual)
    mae0 = statistics.fmean(abs(y-p) for y,p in zip(actual,baseline))
    mae = statistics.fmean(abs(y-p) for y,p in zip(actual,pred))
    rmse0 = math.sqrt(statistics.fmean((y-p)**2 for y,p in zip(actual,baseline)))
    rmse = math.sqrt(statistics.fmean((y-p)**2 for y,p in zip(actual,pred)))
    directional = [1 if (p>0 and y>0) or (p<0 and y<0) else 0
                   for y,p in zip(actual,pred) if abs(p)>1e-12]
    nonzero = sum(abs(p)>1e-12 for p in pred)
    return {
        "status":"OK","bars_after_filter":n,"samples_total":len(samples),
        "train_samples":len(train),"test_samples":len(test),
        "test_start":test[0][0],"test_end":test[-1][0],
        "alpha":alpha,"beta":beta,
        "baseline_mae_pct":mae0*100,"model_mae_pct":mae*100,
        "mae_improvement_pct":((mae0-mae)/mae0*100) if mae0 else None,
        "baseline_rmse_pct":rmse0*100,"model_rmse_pct":rmse*100,
        "directional_accuracy_pct":(statistics.fmean(directional)*100 if directional else None),
        "nonzero_prediction_pct":nonzero/len(pred)*100,
        "weekend_bars_excluded":quality["weekend_bars_excluded"],
        "duplicates":quality["duplicates"],"invalid_ohlc":quality["invalid_ohlc"],
        "model":"OLS: next-24-bar log return ~ intercept + beta * previous-24-bar log return",
        "baseline":"zero return (price unchanged)",
    }


def main():
    archive = DATA / "H1_HISTORY.json.gz"
    if not archive.exists():
        raise SystemExit("Cumulative H1_HISTORY.json.gz not found; run the daily collector first")
    payload = load_archive(archive)
    REPORTS.mkdir(parents=True, exist_ok=True)
    results = {ticker:evaluate_symbol(block["candles"])
               for ticker,block in payload.get("symbols", {}).items()}
    valid = [v for v in results.values() if v.get("status")=="OK"]
    outperform = [t for t,v in results.items()
                  if v.get("status")=="OK" and v["model_mae_pct"] < v["baseline_mae_pct"]]
    summary = {
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "source_archive":str(archive),"source":"Finam technical H1",
        "universe_size":len(results),"symbols_evaluated":len(valid),
        "symbols_outperforming_zero_return_baseline":len(outperform),
        "outperforming_symbols":outperform,
        "median_baseline_mae_pct":statistics.median(v["baseline_mae_pct"] for v in valid) if valid else None,
        "median_model_mae_pct":statistics.median(v["model_mae_pct"] for v in valid) if valid else None,
        "method":{
            "horizon":"next 24 available weekday H1 bars",
            "weekends":"excluded; weekday Finam bars remain technical proxy, not official MOEX session validation",
            "split":"first 70% chronological training; last 30% test with 24-sample embargo",
            "model":"per-symbol OLS mapping previous 24-bar return to next 24-bar return",
            "baseline":"zero return / price unchanged",
            "costs":"not included; no tradability or profitability claim",
            "leakage":"test targets are after chronological split and horizon embargo",
        },
        "results":results,
    }
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out=REPORTS/f"walk-forward-{stamp}.json"
    out.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    csvpath=REPORTS/f"walk-forward-{stamp}.csv"
    fields=["ticker","status","bars_after_filter","samples_total","train_samples","test_samples",
            "baseline_mae_pct","model_mae_pct","mae_improvement_pct","baseline_rmse_pct",
            "model_rmse_pct","directional_accuracy_pct","nonzero_prediction_pct",
            "weekend_bars_excluded","duplicates","invalid_ohlc"]
    with csvpath.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=["ticker"]+fields[1:])
        w.writeheader()
        for ticker,v in results.items(): w.writerow({"ticker":ticker,**v})
    print(json.dumps({
        "status":"OK","archive":str(archive),"symbols":len(results),
        "evaluated":len(valid),"outperforming_baseline":len(outperform),
        "median_baseline_mae_pct":summary["median_baseline_mae_pct"],
        "median_model_mae_pct":summary["median_model_mae_pct"],
        "json_report":str(out),"csv_report":str(csvpath),
    },ensure_ascii=False))


if __name__=="__main__":
    main()
