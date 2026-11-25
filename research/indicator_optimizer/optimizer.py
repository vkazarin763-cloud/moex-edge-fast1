#!/usr/bin/env python3
"""Research-only MOEX indicator parameter optimizer. No broker or notification integrations."""
from __future__ import annotations

import argparse
import itertools
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import truststore
truststore.inject_into_ssl()  # use the runner OS trust store; never disable TLS verification
import requests

TICKERS = """AFKS AFLT ALRS BSPB CBOM CHMF CNRU DOMRF ENPG FLOT GAZP GMKN HEAD IRAO LKOH MAGN MDMG MOEX MTSS NLMK NVTK OZON PHOR PLZL POSI RAGR RENI ROSN RTKM RUAL SBER SBERP SNGS SNGSP SVCB T TATN TATNP TRNFP UGLD VKCO VTBR X5 YDEX""".split()
ISS = "https://iss.moex.com/iss"
MSK = ZoneInfo("Europe/Moscow")
DEFAULT_START = "2025-01-01"
ROUND_TRIP_FEE = 0.0026  # conservative legacy estimate; override with verified broker tariff
ROUND_TRIP_SLIPPAGE = 0.0010  # sensitivity assumption, not measured historical spread
HOLD_BARS = 3
MIN_TRADES = 30
SESSION_START = dtime(9, 0)   # main session, after 14-Sep-2026 schedule change
SESSION_END = dtime(19, 0)

def fetch_candles(ticker: str, interval: int, start: str, end: str) -> pd.DataFrame:
    url = f"{ISS}/engines/stock/markets/shares/boards/TQBR/securities/{ticker}/candles.json"
    rows, offset = [], 0
    session = requests.Session()
    while True:
        response = session.get(url, params={"from": start, "till": end, "interval": interval,
                                            "start": offset, "iss.reverse": "false"}, timeout=35)
        response.raise_for_status()
        block = response.json().get("candles", {})
        cols, data = block.get("columns", []), block.get("data", [])
        if not data:
            break
        ix = {name: i for i, name in enumerate(cols)}
        needed = ["open", "high", "low", "close", "volume", "begin"]
        if any(c not in ix for c in needed):
            raise ValueError(f"{ticker}: unexpected ISS candle schema: {cols}")
        rows.extend([[r[ix[c]] for c in needed] for r in data])
        if len(data) < 500:
            break
        offset += len(data)
        time.sleep(0.15)
    if not rows:
        return pd.DataFrame(columns=["open","high","low","close","volume","begin"])
    df = pd.DataFrame(rows, columns=["open","high","low","close","volume","begin"])
    for c in ["open","high","low","close","volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["begin"] = pd.to_datetime(df["begin"], errors="coerce")
    return df

def validate_candles(raw: pd.DataFrame, interval: int, now: datetime | None = None):
    """Return cleaned main-session bars and explicit quality counters."""
    stats = {"raw_rows": int(len(raw)), "duplicates": 0, "invalid_ohlc": 0,
             "null_rows": 0, "incomplete_last": 0, "outside_main_session": 0}
    if raw.empty:
        return raw.copy(), stats
    df = raw.copy()
    stats["null_rows"] = int(df[["open","high","low","close","volume","begin"]].isna().any(axis=1).sum())
    df = df.dropna(subset=["open","high","low","close","volume","begin"])
    stats["duplicates"] = int(df.duplicated("begin").sum())
    df = df.drop_duplicates("begin", keep="last").sort_values("begin")
    valid = ((df[["open","high","low","close"]] > 0).all(axis=1)
             & (df["high"] >= df[["open","close","low"]].max(axis=1))
             & (df["low"] <= df[["open","close","high"]].min(axis=1))
             & (df["volume"] >= 0))
    stats["invalid_ohlc"] = int((~valid).sum())
    df = df.loc[valid].copy()
    now = now or datetime.now(MSK)
    if now.tzinfo is None:
        now = now.replace(tzinfo=MSK)
    # ISS begin timestamps are Moscow local wall time; exclude any still-forming bar.
    local_now = now.astimezone(MSK).replace(tzinfo=None)
    bar_end = df["begin"] + pd.to_timedelta(interval, unit="m")
    incomplete = bar_end > local_now
    stats["incomplete_last"] = int(incomplete.sum())
    df = df.loc[~incomplete].copy()
    times = df["begin"].dt.time
    in_session = (times >= SESSION_START) & ((df["begin"] + pd.to_timedelta(interval, unit="m")).dt.time <= SESSION_END)
    stats["outside_main_session"] = int((~in_session).sum())
    df = df.loc[in_session].reset_index(drop=True)
    return df, stats

def ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False, min_periods=n).mean()

def rsi(close: pd.Series, n: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100/(1+rs)
    out = out.mask((loss == 0) & (gain > 0), 100)
    return out

def macd(close: pd.Series, fast: int, slow: int, signal: int):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig

def adx_di(df: pd.DataFrame, n: int):
    up = df.high.diff()
    down = -df.low.diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = pd.concat([df.high-df.low, (df.high-df.close.shift()).abs(),
                    (df.low-df.close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    pdi = 100 * plus.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr
    mdi = 100 * minus.ewm(alpha=1/n, adjust=False, min_periods=n).mean() / atr
    dx = 100 * (pdi-mdi).abs() / (pdi+mdi).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False, min_periods=n).mean(), pdi, mdi

def candidate_signals(df: pd.DataFrame, family: str, p: dict):
    c, idx = df.close, df.index
    if family == "EMA":
        a, b = ema(c, p["fast"]), ema(c, p["slow"])
        return ((a > b) & (a.shift() <= b.shift())).fillna(False), ((a < b) & (a.shift() >= b.shift())).fillna(False)
    if family == "RSI":
        x = rsi(c, p["period"])
        lo, hi = p["lower"], p["upper"]
        return ((x > lo) & (x.shift() <= lo)).fillna(False), ((x < hi) & (x.shift() >= hi)).fillna(False)
    if family == "MACD":
        a, b = macd(c, p["fast"], p["slow"], p["signal"])
        return ((a > b) & (a.shift() <= b.shift())).fillna(False), ((a < b) & (a.shift() >= b.shift())).fillna(False)
    if family == "ADX_DI":
        ax, plus, minus = adx_di(df, p["period"])
        strength = ax >= p["threshold"]
        return (((plus > minus) & (plus.shift() <= minus.shift()) & strength).fillna(False),
                ((plus < minus) & (plus.shift() >= minus.shift()) & strength).fillna(False))
    if family == "DONCHIAN":
        hi = df.high.rolling(p["period"], min_periods=p["period"]).max().shift()
        lo = df.low.rolling(p["period"], min_periods=p["period"]).min().shift()
        return (c > hi).fillna(False), (c < lo).fillna(False)
    if family == "BOLLINGER":
        mid = c.rolling(p["period"], min_periods=p["period"]).mean()
        sd = c.rolling(p["period"], min_periods=p["period"]).std()
        upper, lower = mid+p["stdev"]*sd, mid-p["stdev"]*sd
        # Mean-reversion re-entry: close crosses back inside an outer band.
        return ((c > lower) & (c.shift() <= lower.shift())).fillna(False), ((c < upper) & (c.shift() >= upper.shift())).fillna(False)
    if family == "ATR_KELTNER":
        n, mult = p["period"], p["multiplier"]
        tr = pd.concat([df.high-df.low, (df.high-df.close.shift()).abs(),
                        (df.low-df.close.shift()).abs()], axis=1).max(axis=1)
        mid = ema(c, p["ema"])
        atr = tr.rolling(n, min_periods=n).mean()
        up, dn = mid+mult*atr, mid-mult*atr
        return ((c > up) & (c.shift() <= up.shift())).fillna(False), ((c < dn) & (c.shift() >= dn.shift())).fillna(False)
    if family == "STOCH":
        n, smooth = p["period"], p["smooth"]
        low = df.low.rolling(n, min_periods=n).min()
        high = df.high.rolling(n, min_periods=n).max()
        k = 100*(c-low)/(high-low).replace(0, np.nan)
        d = k.rolling(smooth, min_periods=smooth).mean()
        return (((k > d) & (k.shift() <= d.shift()) & (k < p["lower"])).fillna(False),
                ((k < d) & (k.shift() >= d.shift()) & (k > p["upper"])).fillna(False))
    raise ValueError(f"Unknown family {family}")

def parameter_grid():
    grids = {
      "EMA": [{"fast":f,"slow":s} for f,s in itertools.product([8,10,12,15,20],[30,40,50,60,80]) if f<s],
      "RSI": [{"period":n,"lower":lo,"upper":hi} for n,lo,hi in itertools.product([7,9,14,21],[25,30,35],[65,70,75]) if lo < hi],
      "MACD": [{"fast":f,"slow":s,"signal":sig} for f,s,sig in [(8,21,5),(12,26,9),(10,30,9),(5,35,5)]],
      "ADX_DI": [{"period":n,"threshold":t} for n,t in itertools.product([10,14,20],[18,20,25,30])],
      "DONCHIAN": [{"period":n} for n in [10,20,30,55]],
      "BOLLINGER": [{"period":n,"stdev":v} for n,v in itertools.product([14,20,30],[1.8,2.0,2.2])],
      "ATR_KELTNER": [{"period":n,"ema":e,"multiplier":m} for n,e,m in itertools.product([10,14,20],[10,20],[1.5,2.0,2.5])],
      "STOCH": [{"period":n,"smooth":s,"lower":lo,"upper":hi} for n,s,lo,hi in [(9,3,20,80),(14,3,20,80),(21,5,20,80),(14,3,25,75)]],
    }
    return grids

def simulate_signals(df, long_sig, short_sig, direction, hold, fee, slippage):
    """Signal on completed close; enter next bar open; exit after hold bars at close."""
    sig = long_sig if direction == 1 else short_sig
    positions = []
    next_allowed = 0
    # Iterate only actual signal indices, not every candle.
    for i in np.flatnonzero(sig.to_numpy(dtype=bool)):
        if i < next_allowed or i + hold >= len(df):
            continue
        entry_i, exit_i = i+1, i+hold
        entry, exitp = float(df.open.iloc[entry_i]), float(df.close.iloc[exit_i])
        if entry <= 0:
            continue
        gross = direction*(exitp-entry)/entry
        net = gross-fee-slippage
        positions.append({"signal_time":str(df.begin.iloc[i]),"entry_time":str(df.begin.iloc[entry_i]),"exit_time":str(df.begin.iloc[exit_i]),
                          "gross_return":gross,"net_return":net,"bars":hold})
        next_allowed = exit_i+1
    return positions

def metrics(trades):
    if not trades:
        return {"trades":0,"win_rate":None,"mean_net":None,"median_net":None,"profit_factor":None,"max_drawdown":None}
    r = np.array([x["net_return"] for x in trades], dtype=float)
    wins, losses = r[r>0], r[r<=0]
    pf = float(wins.sum()/abs(losses.sum())) if len(losses) and abs(losses.sum()) > 1e-12 else (None if not len(wins) else 99.0)
    equity = np.cumprod(1+r)
    peak = np.maximum.accumulate(np.r_[1.0,equity])
    dd = equity/peak[1:]-1
    gross = np.array([x.get("gross_return", np.nan) for x in trades], dtype=float)
    return {"trades":len(r),"win_rate":float((r>0).mean()),"mean_net":float(r.mean()),
            "median_net":float(np.median(r)),"mean_gross":float(np.nanmean(gross)) if np.isfinite(gross).any() else None,
            "median_gross":float(np.nanmedian(gross)) if np.isfinite(gross).any() else None,
            "profit_factor":pf,"max_drawdown":float(dd.min())}

def split_bounds(df):
    n=len(df)
    return int(n*.60), int(n*.80)

def walk_forward_metrics(df, trades, folds=4):
    """Four sequential training-stability blocks; validation and final-test windows are excluded."""
    start_idx = int(len(df) * 0.20)
    end_idx = int(len(df) * 0.60)  # keep all walk-forward stability checks inside training; validation/test remain separate
    edges = np.linspace(start_idx, end_idx, folds + 1, dtype=int)
    output = []
    for fold_no in range(folds):
        lo_idx, hi_idx = edges[fold_no], edges[fold_no+1]
        lo = pd.Timestamp(df.begin.iloc[lo_idx])
        hi = pd.Timestamp(df.begin.iloc[hi_idx]) if hi_idx < len(df) else pd.Timestamp(df.begin.iloc[-1]) + pd.Timedelta(days=1)
        block = [t for t in trades if lo <= pd.Timestamp(t["signal_time"]) and pd.Timestamp(t["exit_time"]) < hi]
        stat = metrics(block)
        output.append({"fold":fold_no+1,"start":str(lo),"end_exclusive":str(hi),**stat})
    return output

def evaluate(df, family, params, direction, fee, slippage, hold):
    long_sig, short_sig = candidate_signals(df, family, params)
    trades=simulate_signals(df,long_sig,short_sig,direction,hold,fee,slippage)
    train_end, val_end=split_bounds(df)
    def in_range(items, lo, hi):
        # Keep each trade wholly inside one partition; never let a train trade exit in validation/test.
        return [t for t in items if lo <= pd.Timestamp(t["signal_time"]) and pd.Timestamp(t["exit_time"]) < hi]
    times=df.begin
    train=in_range(trades,times.iloc[0],times.iloc[train_end]) if train_end else []
    val=in_range(trades,times.iloc[train_end],times.iloc[val_end]) if val_end>train_end else []
    test=in_range(trades,times.iloc[val_end],times.iloc[-1]+pd.Timedelta(days=1)) if val_end<len(df) else []
    return metrics(train),metrics(val),metrics(test),trades,test

def run(args):
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    end=args.end or datetime.now(MSK).date().isoformat()
    all_rows, quality=[],[]
    pooled_test={}
    grids=parameter_grid()
    defaults={"EMA":{"fast":20,"slow":50},"RSI":{"period":14,"lower":30,"upper":70},
      "MACD":{"fast":12,"slow":26,"signal":9},"ADX_DI":{"period":14,"threshold":20},
      "DONCHIAN":{"period":20},"BOLLINGER":{"period":20,"stdev":2.0},
      "ATR_KELTNER":{"period":14,"ema":20,"multiplier":2.0},"STOCH":{"period":14,"smooth":3,"lower":20,"upper":80}}
    for interval in args.intervals:
      for ticker in args.tickers:
        print(f"FETCH {ticker} {interval}m",flush=True)
        try:
          cache_path=Path(args.cache_dir)/f"{ticker}_{interval}_{args.start}_{end}.csv"
          if cache_path.exists() and not args.refresh:
            raw=pd.read_csv(cache_path)
          else:
            raw=fetch_candles(ticker,interval,args.start,end)
            cache_path.parent.mkdir(parents=True,exist_ok=True)
            raw.to_csv(cache_path,index=False)
          df,q=validate_candles(raw,interval)
          quality.append({"ticker":ticker,"interval":interval,**q,"clean_rows":len(df),
                          "first":str(df.begin.min()) if len(df) else None,"last":str(df.begin.max()) if len(df) else None})
          if len(df)<250: continue
          for family,params_list in grids.items():
            for params in params_list:
              for direction in [1,-1]:
                tr,va,te,trades,test_trades=evaluate(df,family,params,direction,args.fee,args.slippage,args.hold_bars)
                if tr["trades"] < args.min_trades: continue
                param_key=json.dumps(params,sort_keys=True)
                all_rows.append({"ticker":ticker,"interval":interval,"family":family,
                  "direction":"LONG" if direction==1 else "SHORT","params":param_key,
                  "is_baseline":params==defaults[family],"train":tr,"validation":va,"test":te,
                  "walk_forward":walk_forward_metrics(df,trades)})
                pool_key=(interval,family,param_key,direction)
                pooled_test.setdefault(pool_key,[]).extend(test_trades)
        except Exception as exc:
          quality.append({"ticker":ticker,"interval":interval,"error":str(exc)})
          print(f"ERROR {ticker} {interval}: {exc}",flush=True)
    qdf=pd.DataFrame(quality); qdf.to_csv(out/"data_quality.csv",index=False)
    pooled_rows=[]
    for (interval,family,param_key,direction),trades in pooled_test.items():
      pooled_rows.append({"interval":interval,"family":family,"params":param_key,
        "direction":"LONG" if direction==1 else "SHORT","test":metrics(trades)})
    pd.DataFrame(pooled_rows).to_json(out/"pooled_test_results.json",orient="records",force_ascii=False,indent=2)
    if not all_rows:
      download_errors=sum(1 for item in quality if "error" in item)
      expected_downloads=len(args.tickers)*len(args.intervals)
      if download_errors == expected_downloads:
        summary={"status":"data_fetch_failed","download_errors":download_errors,
                 "note":"Every MOEX ISS candle request failed; no strategy statistics were calculated."}
        (out/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
        raise RuntimeError("All MOEX ISS data downloads failed; refusing to report an empty successful run.")
      (out/"summary.json").write_text(json.dumps({"status":"no_eligible_results","download_errors":download_errors,
        "note":"No candidate reached minimum training trade count. Check data_quality.csv for coverage and errors."},indent=2),encoding="utf-8")
      return
    results=pd.DataFrame(all_rows)
    # Select only on validation, never on final test. Require positive validation expectancy.
    results["val_mean"]=results.validation.map(lambda x: x["mean_net"] if x["mean_net"] is not None else -999)
    results["val_pf"]=results.validation.map(lambda x: x["profit_factor"] if x["profit_factor"] is not None else 0)
    results["val_trades"]=results.validation.map(lambda x: x["trades"])
    results["wf_mean_net"]=results.walk_forward.map(lambda xs: float(np.mean([x["mean_net"] for x in xs if x["trades"]>=5 and x["mean_net"] is not None])) if any(x["trades"]>=5 and x["mean_net"] is not None for x in xs) else -999)
    results["wf_active_folds"]=results.walk_forward.map(lambda xs: sum(1 for x in xs if x["trades"]>=5))
    results=results.sort_values(["val_mean","val_pf","val_trades"],ascending=False)
    results.to_json(out/"candidate_results.json",orient="records",force_ascii=False,indent=2)
    selected=results[(results.val_trades>=10)&(results.val_mean>0)&(results.wf_active_folds>=3)&(results.wf_mean_net>0)].groupby(["interval","family","direction"],as_index=False).head(3)
    selected.to_json(out/"validation_shortlist.json",orient="records",force_ascii=False,indent=2)
    summary={"status":"completed","tickers":len(TICKERS),"intervals":[10,60],"candidate_rows":len(results),"data_errors":sum(1 for item in quality if "error" in item),
      "shortlisted_rows":len(selected),"fee_round_trip":args.fee,"slippage_round_trip":args.slippage,
      "holding_bars":args.hold_bars,"selection":"train minimum trades; validation positive mean net return; final test untouched",
      "important":"These are per-ticker exploratory candidates, not proof of profitability. Aggregate and walk-forward stability review is required before any production use."}
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--start",default=DEFAULT_START)
    p.add_argument("--end",default=None)
    p.add_argument("--fee",type=float,default=ROUND_TRIP_FEE)
    p.add_argument("--slippage",type=float,default=ROUND_TRIP_SLIPPAGE)
    p.add_argument("--output",default="optimizer_output")
    p.add_argument("--cache-dir",default="data/indicator_optimizer_cache")
    p.add_argument("--refresh",action="store_true")
    p.add_argument("--tickers",nargs="+",default=TICKERS)
    p.add_argument("--intervals",nargs="+",type=int,choices=[10,60],default=[10,60])
    p.add_argument("--min-trades",type=int,default=MIN_TRADES)
    p.add_argument("--hold-bars",type=int,default=HOLD_BARS)
    args=p.parse_args()
    if args.min_trades<1 or args.hold_bars<1: p.error("min-trades and hold-bars must be positive")
    if args.fee<0 or args.slippage<0: p.error("fee/slippage must be non-negative")
    run(args)

if __name__=="__main__":
    main()
