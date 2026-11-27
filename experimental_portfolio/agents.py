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
    body={"model":model,"temperature":0.1,"max_tokens":450,"response_format":{"type":"json_object"},
      "messages":[{"role":"system","content":"You are a read-only portfolio research reviewer. Never invent prices, facts or performance. Do not instruct the user to trade or place orders. Never change portfolio weights. Return JSON with keys summary (string), risks (array), questions (array)."},
      {"role":"user","content":prompt}]}
    req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={"Authorization":f"Bearer {key}",
      "Content-Type":"application/json","HTTP-Referer":"https://github.com","X-Title":"Experimental Paper Portfolio"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=35) as response: result=json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail=""
        try:
            raw=exc.read().decode("utf-8","replace")
            parsed=json.loads(raw)
            err=parsed.get("error",{})
            if isinstance(err,dict): detail=str(err.get("message") or err.get("code") or "")
            elif isinstance(err,str): detail=err
        except Exception: pass
        detail=re.sub(r"(?i)bearer\s+\S+","Bearer [redacted]",detail)
        detail=re.sub(r"(?i)(api[_ -]?key|token)\s*[:=]\s*\S+",r"\1=[redacted]",detail)
        raise RuntimeError(f"provider_http_{exc.code}:{detail[:160]}") from None
    except Exception as exc: raise RuntimeError(f"provider_request_failed:{type(exc).__name__}") from None
    try: parsed=json.loads(result["choices"][0]["message"]["content"])
    except (KeyError,IndexError,TypeError,json.JSONDecodeError): raise RuntimeError("provider_returned_invalid_json") from None
    if not isinstance(parsed,dict) or not isinstance(parsed.get("summary"),str) or not isinstance(parsed.get("risks",[]),list) or not isinstance(parsed.get("questions",[]),list):
        raise RuntimeError("provider_response_schema_invalid")
    return {"summary":parsed["summary"][:1200],"risks":[str(x)[:300] for x in parsed.get("risks",[])[:5]],
      "questions":[str(x)[:300] for x in parsed.get("questions",[])[:5]]}

def _local_review(role:str,report:dict[str,Any])->dict[str,Any]:
    """Deterministic specialist fallback; explicitly not an LLM-generated opinion."""
    performance=report.get("performance") or {}
    holdings=report.get("holdings") or []
    errors=report.get("data_errors") or {}
    stale=report.get("stale_symbols") or []
    summary="Quantitative evidence is unavailable; no conclusion is drawn." 
    risks=[]; questions=[]
    if role=="market_analyst":
        classes=sorted({x.get("asset_class","unknown") for x in holdings})
        summary=f"Portfolio status: {report.get('status','UNKNOWN')}. Current holdings: {len(holdings)}; represented asset classes: {', '.join(classes) if classes else 'none'}. Cash weight: {report.get('cash_weight','UNKNOWN')}."
        if len(classes)<2: risks.append("Current holdings do not span multiple asset classes.")
        if report.get("status")!="READY": risks.append("Market data status is not READY; current allocation should be treated as unavailable.")
        questions.append("Are the ETF proxies and their exchange calendars representative of the intended global universe?")
    elif role=="portfolio_researcher":
        summary=f"Model: {(report.get('portfolio_model') or {}).get('name','UNKNOWN')}. Backtest observations: {performance.get('observations','UNKNOWN')}; total return: {performance.get('total_return','UNKNOWN')}; SPY benchmark return: {(report.get('benchmark_spy_buy_and_hold') or {}).get('total_return','UNKNOWN')}."
        if performance.get("observations",0)<252: risks.append("The available evaluation window is shorter than one full trading year.")
        risks.append("The strategy is a fixed momentum/trend baseline; it has not passed independent out-of-sample approval.")
        questions.append("Does the strategy remain robust after a longer prospective paper-trading period and stressed transaction costs?")
    else:
        summary=f"Observed maximum drawdown: {performance.get('max_drawdown','UNKNOWN')}; stale instruments: {len(stale)}; instruments with data errors: {len(errors)}."
        if stale: risks.append("At least one instrument has stale daily data.")
        if errors: risks.append("Some requested instruments failed data validation or download.")
        if report.get("derivatives",{}).get("status")!="IN_NAV": risks.append("Options and futures are excluded from NAV pending executable quotes and contract-level risk modeling.")
        questions.append("Are transaction costs, dividends, currency exposure and ETF liquidity sufficiently represented?")
    return {"summary":summary,"risks":risks,"questions":questions}

def run_reviewers(report:dict[str,Any])->dict[str,Any]:
    openrouter=os.getenv("OPENROUTER_API_KEY","").strip(); groq=os.getenv("GROQ_API_KEY","").strip()
    or_model=os.getenv("OPENROUTER_MODEL","openrouter/free"); groq_model=os.getenv("GROQ_MODEL","openai/gpt-oss-20b")
    context={k:report.get(k) for k in ("generated_at_utc","status","period","performance","benchmark_spy_buy_and_hold","holdings","cash_weight","stale_symbols","data_errors","portfolio_model","limitations")}
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
        if result is not None:
            reviews[role]={"status":"COMPLETED","engine":"llm","provider":provider,"model":model,"review":result}
        else:
            reviews[role]={"status":"COMPLETED","engine":"local_deterministic","review":_local_review(role,report)}
            diagnostics[role]=error
    llm_count=sum(x.get("engine")=="llm" for x in reviews.values())
    local_count=len(ROLES)-llm_count
    if llm_count==len(ROLES): status="LLM_COMPLETE"
    elif llm_count: status="MIXED_LLM_AND_LOCAL"
    elif openrouter or groq: status="LOCAL_FALLBACK_AFTER_PROVIDER_FAILURE"
    else: status="LOCAL_DETERMINISTIC_ONLY"
    return {"status":status,"agents_expected":len(ROLES),"agents_completed":len(reviews),
      "llm_agents_completed":llm_count,"local_agents_completed":local_count,
      "provider_diagnostics":diagnostics,"reviews":reviews,
      "policy":"LLM and local reviewers are commentary-only. They cannot change NAV, holdings, signals or authorize real trading."}
