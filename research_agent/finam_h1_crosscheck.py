"""Read-only comparison of completed Finam and MOEX H1 candles."""
from __future__ import annotations
import argparse, json, os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .finam_market_data import FinamMarketDataClient
from .moex_iss import fetch_candles

MOSCOW=ZoneInfo("Europe/Moscow")
DEFAULT_TICKERS=["AFKS","AFLT","ALRS","BSPB","CBOM","CHMF","CNRU","DOMRF","ENPG","FLOT","GAZP","GMKN","HEAD","IRAO","LKOH","MAGN","MDMG","MOEX","MTSS","NLMK","NVTK","OZON","PHOR","PLZL","POSI","RAGR","RENI","ROSN","RTKM","RUAL","SBER","SBERP","SNGS","SNGSP","SVCB","T","TATN","TATNP","TRNFP","UGLD","VKCO","VTBR","X5","YDEX"]

def _local_key(ts):
    if ts.tzinfo is None: return ts.replace(second=0,microsecond=0)
    return ts.astimezone(MOSCOW).replace(tzinfo=None,second=0,microsecond=0)

def compare_h1_series(moex_rows, finam_rows, now=None):
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None: raise ValueError("now must be timezone-aware")
    current=current.astimezone(timezone.utc)
    moex={}
    for row in moex_rows:
        if _local_key(row.timestamp).replace(minute=0) + timedelta(hours=1) > current.astimezone(MOSCOW).replace(tzinfo=None): continue
        key=_local_key(row.timestamp)
        if key in moex: raise ValueError(f"Duplicate MOEX H1 timestamp: {key.isoformat()}")
        moex[key]=row
    finam={}
    for row in finam_rows:
        if row.is_data_snapshot is True: continue
        if row.timestamp + timedelta(hours=1) > current: continue
        key=_local_key(row.timestamp)
        if key in finam: raise ValueError(f"Duplicate Finam H1 timestamp: {key.isoformat()}")
        finam[key]=row
    overlap=sorted(set(moex)&set(finam))
    comparisons=[]
    for key in overlap:
        a,b=moex[key],finam[key]
        prices={}
        for field in ("open","high","low","close"):
            av,bv=float(getattr(a,field)),float(getattr(b,field))
            prices[field]={"moex":av,"finam":bv,"absolute_difference":bv-av,
                "difference_pct_of_moex":(bv-av)/av*100 if av else None}
        av,bv=float(a.volume),float(b.volume)
        comparisons.append({"timestamp_moscow":key.isoformat(),"prices":prices,
            "volume":{"moex":av,"finam":bv,"absolute_difference":bv-av,
            "difference_pct_of_moex":(bv-av)/av*100 if av else None},
            "finam_is_data_snapshot":b.is_data_snapshot})
    return {"status":"NO_OVERLAP" if not overlap else ("DATE_COVERAGE_MATCHES" if set(moex)==set(finam) else "DATE_COVERAGE_DIFFERS"),
        "moex_closed_bars":len(moex),"finam_closed_bars":len(finam),"matched_bars":len(overlap),
        "moex_only_timestamps":[x.isoformat() for x in sorted(set(moex)-set(finam))],
        "finam_only_timestamps":[x.isoformat() for x in sorted(set(finam)-set(moex))],
        "comparisons":comparisons,
        "note":"Only completed bars are compared; snapshot=true and still-open hourly bars are excluded. Unknown snapshot metadata is retained and flagged."}

def run(tickers, days, api_token, source_app_id=None):
    if not 1<=days<=30: raise ValueError("H1 history is limited to 1..30 days")
    now=datetime.now(timezone.utc); start=now-timedelta(days=days)
    client=FinamMarketDataClient.from_api_token(api_token,source_app_id)
    results={}
    for ticker in tickers:
        try:
            moex=fetch_candles(ticker,start.astimezone(MOSCOW).date().isoformat(),
                now.astimezone(MOSCOW).date().isoformat(),interval=60,board="TQBR")
            finam=client.fetch_bars(f"{ticker}@MISX","TIME_FRAME_H1",start,now)
            results[ticker]={"status":"COMPARED","audit":compare_h1_series(moex,finam,now=now)}
        except Exception as exc:
            results[ticker]={"status":"SOURCE_OR_COMPARISON_ERROR","error":str(exc)}
    return {"generated_at_utc":now.isoformat(),"timeframe":"H1","lookback_days":days,
        "symbols":[f"{t}@MISX" for t in tickers],"results":results,
        "safety":"Read-only market data. No account or order methods are called."}

def main():
    p=argparse.ArgumentParser(description="Read-only MOEX ISS vs Finam completed H1 comparison")
    p.add_argument("--days",type=int,default=7); p.add_argument("--tickers",default=",".join(DEFAULT_TICKERS)); p.add_argument("--output",default="finam_moex_h1_crosscheck.json")
    a=p.parse_args(); token=os.environ.get("FINAM_API_TOKEN","").strip()
    if not token: p.error("FINAM_API_TOKEN must be supplied through the environment")
    tickers=[x.strip().upper() for x in a.tickers.split(",") if x.strip()]
    report=run(tickers,a.days,token,os.environ.get("FINAM_SOURCE_APP_ID","").strip() or None)
    Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    compared=sum(x["status"]=="COMPARED" for x in report["results"].values())
    errors=len(report["results"])-compared
    print(f"Finam/MOEX H1 cross-check: {compared} compared, {errors} errors")
    return 0 if compared else 1
if __name__=="__main__": raise SystemExit(main())
