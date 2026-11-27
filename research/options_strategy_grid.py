#!/usr/bin/env python3
"""Exploratory OHLC strategy grid. Historical bid/ask and executable fills unavailable."""
import argparse,json,math
from datetime import datetime
from pathlib import Path
def dt(s):return datetime.fromisoformat(str(s).replace("Z","+00:00"))
def clean(series):
 out=[]
 for x in series or []:
  try:
   b={k:float(x[k]) for k in ("open","high","low","close")};t=dt(x["timestamp"])
   if all(math.isfinite(v) and v>0 for v in b.values()) and b["high"]>=max(b["open"],b["close"],b["low"]) and b["low"]<=min(b["open"],b["close"]):out.append({**b,"t":t})
  except (ValueError,TypeError,KeyError):pass
 return sorted(out,key=lambda x:x["t"])
def ema(a,n):
 k=2/(n+1);r=[]
 for v in a:r.append(v if not r else k*v+(1-k)*r[-1])
 return r
def signals(b):
 c=[x["close"] for x in b];e5,e10,e20=ema(c,5),ema(c,10),ema(c,20);out={}
 for i in range(20,len(b)-1):
  hi5=max(x["high"] for x in b[i-5:i]);hi10=max(x["high"] for x in b[i-10:i])
  for name,ok in {"break5":c[i]>hi5,"break10":c[i]>hi10,"ema5x10":e5[i]>e10[i] and e5[i-1]<=e10[i-1],"ema10x20":e10[i]>e20[i] and e10[i-1]<=e20[i]}.items():
   if ok:out.setdefault(name,[]).append(i)
 return out
def sim(b,idx,hold,sl,tp,cost):
 trades=[];last=-1
 for i in idx:
  e=i+1
  if e>=len(b) or e<=last:continue
  p=b[e]["open"];stop=p*(1-sl/100);target=p*(1+tp/100);end=min(len(b)-1,e+hold);ex=end;px=b[end]["close"];reason="TIME"
  for j in range(e,end+1):
   if b[j]["low"]<=stop:ex=j;px=stop;reason="STOP";break
   if b[j]["high"]>=target:ex=j;px=target;reason="TARGET";break
  gross=(px/p-1)*100;trades.append({"entry_time":b[e]["t"].isoformat(),"exit_time":b[ex]["t"].isoformat(),"gross_pct":round(gross,3),"net_sensitivity_pct":round(gross-cost,3),"reason":reason});last=ex
 return trades
def stat(t):
 if not t:return {"n":0}
 r=[x["net_sensitivity_pct"] for x in t];return {"n":len(r),"win_pct":round(100*sum(x>0 for x in r)/len(r),1),"mean_net_pct":round(sum(r)/len(r),2),"median_net_pct":round(sorted(r)[len(r)//2],2),"total_simple_pct":round(sum(r),2)}
def main():
 p=argparse.ArgumentParser();p.add_argument("input");p.add_argument("--output",default="options-strategy-grid.json");a=p.parse_args();d=json.load(open(a.input));runs=[];groups={}
 for u,item in d.get("underlyings",{}).items():
  contracts=item.get("contract_data",[])
  for probe in item.get("targeted_expiry_probes",[]):
   for c in probe.get("selected_contracts",[]):contracts.append({"symbol":c.get("symbol"),"type":c.get("type"),"expiry":probe.get("requested_expiry"),"history":{"m5":c.get("historical_m5",{}),"h1":c.get("historical_h1",{})}})
  for c in contracts:
   for tf in ("m5","h1"):
    b=clean(c.get("history",{}).get(tf,{}).get("series",[]))
    if len(b)<30:continue
    for rule,idx in signals(b).items():
     for hold in (3,6,12,24):
      for sl in (20,30,50):
       for tp in (30,50,100):
        for cost in (2,5,10):
         t=sim(b,idx,hold,sl,tp,cost)
         if not t:continue
         row={"underlying":u,"option":c["symbol"],"type":c["type"],"expiry":c.get("expiry"),"tf":tf,"rule":rule,"hold":hold,"stop":sl,"target":tp,"cost_pct":cost,"trades":t,"stats":stat(t)};runs.append(row)
         key=(tf,rule,hold,sl,tp,cost);g=groups.setdefault(key,{"trades":[],"contracts":set()});g["trades"]+=t;g["contracts"].add(c["symbol"])
 ranked=[]
 for k,g in groups.items():
  tr=sorted(g["trades"],key=lambda x:x["entry_time"]);cut=int(.7*len(tr))
  ranked.append({"tf":k[0],"rule":k[1],"hold":k[2],"stop":k[3],"target":k[4],"cost_sensitivity_pct":k[5],"contract_count":len(g["contracts"]),"all":stat(tr),"development":stat(tr[:cut]),"chronological_test":stat(tr[cut:])})
 ranked.sort(key=lambda x:(x["chronological_test"].get("mean_net_pct",-999),x["chronological_test"].get("n",0)),reverse=True)
 out={"mode":"exploratory_ohlc_grid","as_of":d.get("as_of_utc"),"instrument_runs":len(runs),"parameter_groups":len(ranked),"top_groups":ranked[:50],"all_runs":runs,"limitations":["Trade OHLC bars are not executable bid/ask.","Cost deductions are sensitivity assumptions, not measured spread or fees.","Current contract selection introduces survivorship/moneyness bias.","Sparse samples and parameter sweep create overfit risk.","Intrabar stop/target conflicts resolve to stop first.","No strategy is approved for live trading."]}
 Path(a.output).write_text(json.dumps(out,indent=2));print(json.dumps({"runs":len(runs),"groups":len(ranked),"top":ranked[:5],"output":a.output},indent=2))
if __name__=="__main__":main()
