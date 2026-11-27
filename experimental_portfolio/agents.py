"""Three read-only AI reviewers. Their output cannot change portfolio state."""
from __future__ import annotations
import json, os, urllib.error, urllib.request
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
    req=urllib.request.Request(url,data=json.dumps(body).encode(),
      headers={"Authorization":f"Bearer {key}","Content-Type":"application/json",
      "HTTP-Referer":"https://github.com","X-Title":"Experimental Paper Portfolio"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=35) as response: result=json.loads(response.read().decode())
    except urllib.error.HTTPError as exc: raise RuntimeError(f"provider_http_{exc.code}") from None
    except Exception as exc: raise RuntimeError(f"provider_request_failed:{type(exc).__name__}") from None
    try: parsed=json.loads(result["choices"][0]["message"]["content"])
    except (KeyError,IndexError,TypeError,json.JSONDecodeError): raise RuntimeError("provider_returned_invalid_json") from None
    if not isinstance(parsed,dict) or not isinstance(parsed.get("summary"),str) or not isinstance(parsed.get("risks",[]),list) or not isinstance(parsed.get("questions",[]),list):
        raise RuntimeError("provider_response_schema_invalid")
    return {"summary":parsed["summary"][:1200],"risks":[str(x)[:300] for x in parsed.get("risks",[])[:5]],
      "questions":[str(x)[:300] for x in parsed.get("questions",[])[:5]]}

def run_reviewers(report:dict[str,Any])->dict[str,Any]:
    openrouter=os.getenv("OPENROUTER_API_KEY","").strip()
    groq=os.getenv("GROQ_API_KEY","").strip()
    or_model=os.getenv("OPENROUTER_MODEL","openrouter/free")
    groq_model=os.getenv("GROQ_MODEL","openai/gpt-oss-20b")
    context={k:report.get(k) for k in ("generated_at_utc","status","period","performance","benchmark_spy_buy_and_hold","holdings","cash_weight","stale_symbols","data_errors","portfolio_model","limitations")}
    if not openrouter and not groq:
        return {"status":"AI_KEYS_NOT_CONFIGURED","agents_expected":len(ROLES),"agents_completed":0,
          "reviews":{},"note":"Deterministic report still runs; AI commentary is not available until a provider key exists."}
    reviews={}
    for role,instruction in ROLES.items():
        prompt=f"ROLE: {role}. {instruction}\nUse only this JSON evidence. Missing facts are UNKNOWN. Do not infer live conditions from EOD data.\n"+json.dumps(context,ensure_ascii=False,separators=(",",":"))
        result=None
        if openrouter:
            try: result=_request(OPENROUTER_URL,openrouter,or_model,prompt); provider,model="openrouter",or_model
            except Exception as exc: error=str(exc)[:100]
        if result is None and groq:
            try: result=_request(GROQ_URL,groq,groq_model,prompt); provider,model="groq_fallback",groq_model
            except Exception as exc: error=str(exc)[:100]
        if result is None: reviews[role]={"status":"FAILED","error":locals().get("error","provider_unavailable")}
        else: reviews[role]={"status":"COMPLETED","provider":provider,"model":model,"review":result}
    completed=sum(x["status"]=="COMPLETED" for x in reviews.values())
    return {"status":"COMPLETED" if completed==len(ROLES) else "PARTIAL" if completed else "FAILED",
      "agents_expected":len(ROLES),"agents_completed":completed,"reviews":reviews,
      "policy":"AI commentary is advisory only; deterministic engine alone calculates NAV and holdings."}
