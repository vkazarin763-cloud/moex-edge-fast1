#!/usr/bin/env python3
"""Exploratory option OHLC grid; no executable bid/ask fill model."""
import argparse, json, math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

MIN_BARS = {"m5": 30, "h1": 30, "d1": 20}
MIN_ALL_TRADES = 20
MIN_TEST_TRADES = 10

def dt(s): return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
def clean(series):
    out=[]
    for x in series or []:
        try:
            z={k:float(x[k]) for k in ("open","high","low","close")}; t=dt(x["timestamp"])
            if all(math.isfinite(v) and v>0 for v in z.values()) and z["high"]>=max(z["open"],z["close"],z["low"]) and z["low"]<=min(z["open"],z["close"]): out.append({**z,"t":t})
        except (ValueError,TypeError,KeyError): pass
    return sorted(out,key=lambda x:x["t"])
def ema(a,n):
    k=2/(n+1); r=[]
    for v in a:r.append(v if not r else k*v+(1-k)*r[-1])
    return r
def signals(b):
    c=[x["close"] for x in b]; e5,e10,e20=ema(c,5),ema(c,10),ema(c,20); out={}
    for i in range(20,len(b)-1):
        hi5=max(x["high"] for x in b[i-5:i]); hi10=max(x["high"] for x in b[i-10:i])
        for name,ok in {"break5":c[i]>hi5,"break10":c[i]>hi10,"ema5x10":e5[i]>e10[i] and e5[i-1]<=e10[i-1],"ema10x20":e10[i]>e20[i] and e10[i-1]<=e20[i-1]}.items():
            if ok: out.setdefault(name,[]).append(i)
    return out
def sim(b,idx,hold,sl,tp,cost):
    trades=[]; last=-1
    for i in idx:
        e=i+1
        if e>=len(b) or e<=last: continue
        p=b[e]["open"]; stop=p*(1-sl/100); target=p*(1+tp/100); end=min(len(b)-1,e+hold); ex=end; px=b[end]["close"]; reason="TIME"
        for j in range(e,end+1):
            if b[j]["low"]<=stop: ex=j; px=stop; reason="STOP"; break
            if b[j]["high"]>=target: ex=j; px=target; reason="TARGET"; break
        gross=(px/p-1)*100
        trades.append({"entry_time":b[e]["t"].isoformat(),"exit_time":b[ex]["t"].isoformat(),"gross_pct":round(gross,3),"net_sensitivity_pct":round(gross-cost,3),"reason":reason}); last=ex
    return trades
def stat(t):
    if not t:return {"n":0,"conclusion":"insufficient_sample"}
    r=[x["net_sensitivity_pct"] for x in t]; n=len(r)
    return {"n":n,"win_pct":round(100*sum(x>0 for x in r)/n,1),"mean_net_pct":round(sum(r)/n,2),"median_net_pct":round(sorted(r)[n//2],2),"total_simple_pct":round(sum(r),2),"conclusion":"exploratory_only" if n>=MIN_ALL_TRADES else "insufficient_sample"}
def main():
    p=argparse.ArgumentParser(); p.add_argument("input"); p.add_argument("--output",default="options-strategy-grid.json"); a=p.parse_args(); d=json.load(open(a.input)); runs=[]; eligibility=[]; groups=defaultdict(list)
    for u,item in d.get("underlyings",{}).items():
        for c in item.get("contract_data",[]):
            for tf,minbars in MIN_BARS.items():
                b=clean(c.get("history",{}).get(tf,{}).get("series",[])); n=len(b)
                eligibility.append({"underlying":u,"option":c.get("symbol"),"type":c.get("type"),"expiry":c.get("expiry"),"timeframe":tf,"valid_bars":n,"minimum_bars":minbars,"eligible":n>=minbars})
                if tf=="d1" or n<minbars: continue
                for rule,idx in signals(b).items():
                    for hold in (3,6,12,24):
                        for sl in (20,30,50):
                            for tp in (30,50,100):
                                for cost in (2,5,10):
                                    tr=sim(b,idx,hold,sl,tp,cost)
                                    if not tr: continue
                                    meta={"underlying":u,"option_type":c.get("type"),"expiry":c.get("expiry"),"tf":tf,"rule":rule,"hold":hold,"stop":sl,"target":tp,"cost_sensitivity_pct":cost}
                                    runs.append({**meta,"option":c.get("symbol"),"trades":tr,"stats":stat(tr)})
                                    key=tuple(meta[k] for k in ("underlying","option_type","expiry","tf","rule","hold","stop","target","cost_sensitivity_pct"))
                                    groups[key].extend(tr)
    all_groups=[]
    for k,tr in groups.items():
        tr=sorted(tr,key=lambda x:x["entry_time"]); cut=int(.7*len(tr)); test=stat(tr[cut:])
        row=dict(zip(("underlying","option_type","expiry","tf","rule","hold","stop","target","cost_sensitivity_pct"),k))
        row.update({"all":stat(tr),"development":stat(tr[:cut]),"chronological_test":test})
        all_groups.append(row)
    all_groups.sort(key=lambda x:(x["chronological_test"].get("mean_net_pct",-999),x["chronological_test"].get("n",0)),reverse=True)
    qualified=[x for x in all_groups if x["all"]["n"]>=MIN_ALL_TRADES and x["chronological_test"]["n"]>=MIN_TEST_TRADES]
    coverage={}
    for tf in MIN_BARS:
        rows=[x for x in eligibility if x["timeframe"]==tf]
        coverage[tf]={"contracts":len(rows),"eligible":sum(x["eligible"] for x in rows),"minimum_bars":MIN_BARS[tf],"median_valid_bars":sorted(x["valid_bars"] for x in rows)[len(rows)//2] if rows else 0}
    out={"mode":"exploratory_ohlc_grid_separated","as_of":d.get("as_of_utc"),"minimum_history_bars":MIN_BARS,"qualification_thresholds":{"all_trades":MIN_ALL_TRADES,"chronological_test_trades":MIN_TEST_TRADES},"coverage":coverage,"contract_timeframe_eligibility":eligibility,"instrument_runs":len(runs),"parameter_groups":len(all_groups),"qualified_group_count":len(qualified),"top_groups":qualified[:50],"diagnostic_candidates_not_ranked":all_groups[:20],"all_runs":runs,"limitations":["Trade OHLC bars are not executable bid/ask.","Cost deductions are sensitivity assumptions, not measured spread or fees.","Current contract selection introduces survivorship/moneyness bias.","Sparse histories and parameter sweep create overfit risk.","CALL and PUT, expiry and underlying results are separated; no pooled ranking.","Groups are ranked only when both full-sample and chronological-test minimum trade counts are met.","Chronological split is within each contract-specific group; small test samples remain inconclusive.","Intrabar stop/target conflicts resolve to stop first.","No strategy is approved for live trading."]}
    Path(a.output).write_text(json.dumps(out,indent=2)); print(json.dumps({"runs":len(runs),"groups":len(all_groups),"qualified_groups":len(qualified),"coverage":coverage,"diagnostic_candidates":all_groups[:5],"output":a.output},indent=2))
if __name__=="__main__": main()
