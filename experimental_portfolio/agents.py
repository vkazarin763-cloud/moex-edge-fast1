"""Independent AI reviewers with transparent deterministic fallback.

LLM text is commentary only. It never creates or changes portfolio positions.
"""
from __future__ import annotations
import json,os,re,urllib.error,urllib.request
from typing import Any

OPENROUTER_URL="https://openrouter.ai/api/v1/chat/completions"
GROQ_URL="https://api.groq.com/openai/v1/chat/completions"
ROLES={
 "market_analyst":"Describe market breadth, asset-class concentration and notable changes using only supplied facts.",
 "portfolio_researcher":"Critique the deterministic strategy and identify evidence still missing.",
 "risk_auditor":"Act as a skeptical independent risk auditor. Look for data gaps, stale prices, concentration and drawdown limitations.",
}
def _request(url:str,key:str,model:str,prompt:str)->dict[str,Any]:
    body={"model":model,"temperature":0.1,"max_completion_tokens":450,
      "reasoning_format":"hidden","reasoning_effort":"low",
      "response_format":{"type":"json_object"},
      "messages":[{"role":"system","content":"You are a read-only portfolio research reviewer. Never invent prices, facts or performance. Do not instruct the user to trade or place orders. Never change portfolio weights. Return JSON with keys summary (string), risks (array), questions (array)."},
      {"role":"user","content":prompt}]}
    req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={"Authorization":f"Bearer {key}",
      "Content-Type":"application/json","User-Agent":"MOEX-EDGE-Portfolio-Research/1.0"},method="POST")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req,timeout=45) as response: result=json.loads(response.read().decode())
            break
        except urllib.error.HTTPError as exc:
            raw=""
            try: raw=exc.read().decode("utf-8","replace")
            except Exception: pass
            detail=""
            try:
                payload=json.loads(raw)
                err=payload.get("error",{})
                if isinstance(err,dict): detail=str(err.get("message") or err.get("code") or payload.get("message") or "")
                elif isinstance(err,str): detail=err
                else: detail=str(payload.get("message") or "")
            except Exception: detail=raw[:200]
            detail=re.sub(r"(?i)bearer\\s+\\S+","Bearer [redacted]",detail)
            detail=re.sub(r"(?i)(api[_ -]?key|token)\\s*[:=]\\s*\\S+",r"\\1=[redacted]",detail)
            if exc.code==429 and attempt<3:
                try: delay=max(1.0,min(float(exc.headers.get("Retry-After","2")),30.0))
                except (TypeError,ValueError): delay=min(2**attempt,30.0)
                time.sleep(delay); continue
            raise RuntimeError(f"provider_http_{exc.code}:{detail[:180]}") from None
        except Exception as exc: raise RuntimeError(f"provider_request_failed:{type(exc).__name__}") from None
    try: parsed=json.loads(result["choices"][0]["message"]["content"])
    except (KeyError,IndexError,TypeError,json.JSONDecodeError): raise RuntimeError("provider_returned_invalid_json") from None
    if not isinstance(parsed,dict) or not isinstance(parsed.get("summary"),str) or not isinstance(parsed.get("risks",[]),list) or not isinstance(parsed.get("questions",[]),list):
        raise RuntimeError("provider_response_schema_invalid")
    return {"summary":parsed["summary"][:1200],"risks":[str(x)[:300] for x in parsed.get("risks",[])[:5]],
      "questions":[str(x)[:300] for x in parsed.get("questions",[])[:5]]}

def _local_review(role:str,report:dict[str,Any])->dict[str,Any]:
    """Deterministic specialist fallback; explicitly not an LLM-generated opinion."""
    performance=(report.get("historical_backtest") or {}).get("performance") or report.get("performance") or {}
    paper=report.get("paper_portfolio") or {}
    holdings=report.get("holdings") or []
    errors=report.get("data_errors") or {}
    stale=report.get("stale_symbols") or []
    summary="Quantitative evidence is unavailable; no conclusion is drawn."
    risks=[]; questions=[]
    if role=="market_analyst":
        classes=sorted({x.get("asset_class","unknown") for x in holdings})
        summary=f"Forward paper status: {paper.get('status','UNKNOWN')}. Prospective holdings: {len(holdings)}; asset classes: {', '.join(classes) if classes else 'none'}. Cash weight: {report.get('cash_weight','UNKNOWN')}."
        if len(classes)<2 and holdings: risks.append("Prospective holdings currently span fewer than two asset classes.")
        if report.get("status")!="READY": risks.append("Market data status is not READY; portfolio marks may be unavailable.")
        questions.append("Are the ETF proxies and their exchange calendars representative of the intended global universe?")
    elif role=="portfolio_researcher":
        period=(report.get("historical_backtest") or {}).get("period") or {}
        benchmark=(report.get("historical_backtest") or {}).get("benchmark_spy_buy_and_hold") or {}
        summary=f"Historical backtest: {period.get('from','UNKNOWN')} to {period.get('till','UNKNOWN')}; total return {performance.get('total_return','UNKNOWN')}; SPY benchmark {benchmark.get('total_return','UNKNOWN')}. Forward paper NAV index: {paper.get('nav_index','UNKNOWN')}."
        risks.append("Historical backtest is not independent out-of-sample approval.")
        questions.append("Does the strategy remain robust after a longer prospective paper-trading period and stressed transaction costs?")
    else:
        summary=f"Forward paper maximum drawdown: {paper.get('max_drawdown','UNKNOWN')}; historical backtest maximum drawdown: {performance.get('max_drawdown','UNKNOWN')}; stale instruments: {len(stale)}; data errors: {len(errors)}."
        if stale: risks.append("At least one instrument has stale daily data.")
        if errors: risks.append("Some requested instruments failed data validation or download.")
        risks.append("Options and futures are excluded from NAV pending executable quotes and contract-level risk modeling.")
        questions.append("Are transaction costs, dividends, currency exposure and ETF liquidity sufficiently represented?")
    return {"summary":summary,"risks":risks,"questions":questions}

def run_reviewers(report:dict[str,Any])->dict[str,Any]:
    openrouter=os.getenv("OPENROUTER_API_KEY","").strip(); groq=os.getenv("GROQ_API_KEY","").strip()
    or_model=os.getenv("OPENROUTER_MODEL","openrouter/free"); groq_model=os.getenv("GROQ_MODEL","openai/gpt-oss-20b")
    context={k:report.get(k) for k in ("generated_at_utc","status","period","performance","historical_backtest","paper_portfolio","benchmark_spy_buy_and_hold","holdings","cash_weight","stale_symbols","data_errors","portfolio_model","limitations")}
    reviews={}; diagnostics={}
    for role,instruction in ROLES.items():
        prompt=f"ROLE: {role}. {instruction}\nUse only this JSON evidence. Missing facts are UNKNOWN. Do not infer live conditions from EOD data.\n"+json.dumps(context,ensure_ascii=False,separators=(",",":"))
        result=None; provider=None; model=None; error="provider_key_not_configured"
        if openrouter:
            try: result=_request(OPENROUTER_URL,openrouter,or_model,prompt); provider,model="openrouter",or_model
            except Exception as exc: error=str(exc)[:220]
        if result is None and groq:
            try: result=_request(GROQ_URL,groq,groq_model,prompt); provider,model="groq_fallback",groq_model
            except Exception as exc: error=str(exc)[:220]
        if result is not None: reviews[role]={"status":"COMPLETED","engine":"llm","provider":provider,"model":model,"review":result}
        else:
            reviews[role]={"status":"COMPLETED","engine":"local_deterministic","review":_local_review(role,report)}
            diagnostics[role]=error
    llm_count=sum(x.get("engine")=="llm" for x in reviews.values())
    local_count=len(ROLES)-llm_count
    status="LLM_COMPLETE" if llm_count==len(ROLES) else "MIXED_LLM_AND_LOCAL" if llm_count else "LOCAL_FALLBACK_AFTER_PROVIDER_FAILURE" if openrouter or groq else "LOCAL_DETERMINISTIC_ONLY"
    return {"status":status,"agents_expected":len(ROLES),"agents_completed":len(reviews),
      "llm_agents_completed":llm_count,"local_agents_completed":local_count,
      "provider_diagnostics":diagnostics,"reviews":reviews,
      "policy":"LLM and local reviewers are commentary-only. They cannot change NAV, holdings, signals or authorize real trading."}
