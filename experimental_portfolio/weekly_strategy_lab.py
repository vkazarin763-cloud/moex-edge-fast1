"""Deterministic weekly strategy lab. Pure functions; no data fetching or broker calls."""
from __future__ import annotations
from typing import Any
from datetime import date

STRATEGIES = (
    "buy_hold",
    "sma_trend", "sma_trend_10w", "sma_trend_40w",
    "momentum_13w", "momentum_26w", "momentum_52w",
    "mean_reversion_4w", "mean_reversion_2w", "mean_reversion_8w",
    "breakout_13w", "breakout_26w", "breakout_52w",
)
DEFAULT_ONE_WAY_COST = 0.001


def validate_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned=[]; seen=set()
    for row in bars:
        day=str(row.get("date",""))
        try: values=[float(row[k]) for k in ("open","high","low","close")]
        except (KeyError,TypeError,ValueError): continue
        o,h,l,c=values
        if not day or day in seen or any(v<=0 for v in values) or h<max(o,l,c) or l>min(o,h,c): continue
        seen.add(day); cleaned.append({"date":day,"open":o,"high":h,"low":l,"close":c})
    return sorted(cleaned,key=lambda r:r["date"])


def _strategy_spec(strategy: str) -> tuple[str, int]:
    if strategy == "buy_hold": return ("buy_hold", 0)
    aliases = {
        "sma_trend": ("sma", 20),
        "momentum_13w": ("momentum", 13),
        "mean_reversion_4w": ("mean_reversion", 4),
        "breakout_13w": ("breakout", 13),
    }
    if strategy in aliases: return aliases[strategy]
    for prefix, family in (
        ("sma_trend_", "sma"),
        ("momentum_", "momentum"),
        ("mean_reversion_", "mean_reversion"),
        ("breakout_", "breakout"),
    ):
        if strategy.startswith(prefix) and strategy.endswith("w"):
            try: window=int(strategy[len(prefix):-1])
            except ValueError: break
            if window in (2, 8, 10, 13, 26, 40, 52):
                return (family, window)
    raise ValueError(f"unknown_strategy:{strategy}")


def signal_series(bars: list[dict[str,Any]], strategy: str) -> list[int]:
    family, window = _strategy_spec(strategy)
    closes=[r["close"] for r in bars]; signals=[0]*len(closes)
    if family=="buy_hold": return [1]*len(closes)
    for i,c in enumerate(closes):
        if family=="sma" and i>=window-1:
            signals[i]=int(c>sum(closes[i-window+1:i+1])/window)
        elif family=="momentum" and i>=window:
            signals[i]=int(c>closes[i-window])
        elif family=="mean_reversion" and i>=window:
            signals[i]=int(c<closes[i-window])
        elif family=="breakout" and i>=window:
            signals[i]=int(c>max(closes[i-window:i]))
    return signals


def backtest(
    bars:list[dict[str,Any]],
    strategy:str,
    one_way_cost:float=DEFAULT_ONE_WAY_COST,
    evaluation_start:str|None=None,
    evaluation_end:str|None=None,
)->dict[str,Any]:
    bars=validate_bars(bars)
    _strategy_spec(strategy)
    if len(bars)<2: return {"strategy":strategy,"bars":len(bars),"status":"INSUFFICIENT_DATA"}
    if not 0<=one_way_cost<0.1: raise ValueError("invalid_cost")
    signals=signal_series(bars,strategy); returns=[]; dates=[]; exposure=[]
    for i in range(1,len(bars)):
        if evaluation_start and bars[i]["date"] < evaluation_start: continue
        if evaluation_end and bars[i]["date"] >= evaluation_end: continue
        position=signals[i-1]
        gross=bars[i]["close"]/bars[i-1]["close"]-1
        turnover=abs(position-signals[i-2]) if i>=2 else abs(position)
        returns.append(position*gross-turnover*one_way_cost)
        dates.append(bars[i]["date"]); exposure.append(position)
    if not returns:
        return {"strategy":strategy,"bars":len(bars),"status":"INSUFFICIENT_EVALUATION_WINDOW"}
    nav=peak=1.0; maxdd=0.0
    for r in returns: nav*=1+r; peak=max(peak,nav); maxdd=min(maxdd,nav/peak-1)
    years=max((date.fromisoformat(dates[-1])-date.fromisoformat(dates[0])).days/365.25,1/52)
    mean=sum(returns)/len(returns); variance=sum((r-mean)**2 for r in returns)/max(len(returns)-1,1)
    vol=variance**0.5*52**0.5
    # A Sharpe ratio on near-zero-volatility NAV series is numerically unstable
    # and can look spectacular without representing investable risk-adjusted alpha.
    sharpe_status="LOW_VOLATILITY_UNRELIABLE" if vol<0.05 else "OK"
    sharpe=mean/(variance**0.5)*52**0.5 if variance>0 and sharpe_status=="OK" else None
    return {"strategy":strategy,"status":"OK","bars":len(bars),"evaluation_bars":len(returns),
      "period":{"from":dates[0],"to":dates[-1]},"total_return":nav-1,
      "cagr":nav**(1/years)-1 if nav>0 else -1,"max_drawdown":maxdd,
      "annualized_volatility":vol,"sharpe_rf0":sharpe,"sharpe_status":sharpe_status,
      "exposure_fraction":sum(exposure)/len(exposure),
      "trades_or_rebalances":sum(abs(signals[i]-signals[i-1]) for i in range(1,len(signals))),
      "one_way_cost":one_way_cost,"ending_nav":nav}


def compare(
    bars:list[dict[str,Any]],
    costs=(0.001,0.0025,0.005),
    evaluation_start:str|None=None,
)->list[dict[str,Any]]:
    return [
        {**backtest(bars,s,c,evaluation_start=evaluation_start),"cost_stress":c}
        for c in costs for s in STRATEGIES
    ]


def walk_forward_compare(
    bars:list[dict[str,Any]],
    costs=(0.001,0.0025,0.005),
    warmup_bars:int=104,
    fold_bars:int=52,
    min_fold_bars:int=26,
)->list[dict[str,Any]]:
    """Sequential fixed-rule holdouts; indicators use only bars before each return."""
    clean=validate_bars(bars)
    if warmup_bars<52 or fold_bars<13 or min_fold_bars<13 or min_fold_bars>fold_bars:
        raise ValueError("invalid_walk_forward_window")
    results=[]
    fold_number=0
    for start_idx in range(warmup_bars,len(clean),fold_bars):
        end_idx=min(start_idx+fold_bars,len(clean))
        if end_idx-start_idx<min_fold_bars: continue
        fold_number+=1
        start=clean[start_idx]["date"]
        end=clean[end_idx]["date"] if end_idx<len(clean) else None
        for cost in costs:
            for strategy in STRATEGIES:
                result=backtest(clean,strategy,cost,evaluation_start=start,evaluation_end=end)
                results.append({**result,"fold":fold_number,"warmup_bars":start_idx,
                    "test_from":start,"test_to":result.get("period",{}).get("to"),
                    "cost_stress":cost,"validation":"sequential_fixed_rule_holdout"})
    return results
