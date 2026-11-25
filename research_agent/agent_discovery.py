"""Free-tier Groq agents propose strategy ideas and shortlist deterministic MOEX signals.

The agents never calculate or authoritatively publish prices/signals. Every signal
proposal must be an exact member of the deterministic D1/H1 scan. Strategy ideas
are exploratory suggestions from the existing frozen strategy/timeframe catalog;
they are not backtest results or approvals.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .agent_signal_verifier import verify_agent_proposals

API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_OPENROUTER_MODEL = "openrouter/free"
STRATEGIES = ["Donchian20", "EMA20x50", "RSI14Trend50", "MACD12x26", "Keltner20x2ATR"]
DIRECTIONS = ["LONG", "SHORT"]
FORECAST_ASSESSMENTS = ["AGREES", "CONTRADICTS", "NEUTRAL", "INSUFFICIENT_EVIDENCE"]
TIMEFRAME_CONFIGS = {
    "A": ["D1", "H1"],
    "B": ["W1", "D1", "H1"],
    "C": ["D1", "H4", "H1"],
    "D": ["W1", "D1", "H4", "H1"],
    "E": ["W1", "D1", "H4", "H1", "M15"],
}
ROLES = {
    "signal_hunter": (
        "Find the strongest current candidate signals. Select ONLY exact rows from "
        "candidate_signals. Never invent a ticker, direction, strategy or D1 bar-end. "
        "Independently consider whether an existing strategy/timeframe configuration "
        "deserves a falsifiable research test; return a hypothesis only if justified."
    ),
    "strategy_scout": (
        "Explore which existing frozen strategy families and timeframe configurations "
        "deserve the next deterministic research test. You may shortlist current signals "
        "only when an exact candidate row supports them. Do not invent performance. "
        "Independently nominate only testable hypotheses supported by the supplied context."
    ),
    "skeptical_reviewer": (
        "Act as an adversarial reviewer. Reject weak, conflicting or poorly confirmed "
        "candidates. Prefer an empty shortlist over unsupported proposals. Independently "
        "consider testable strategy/timeframe hypotheses, but nominate one only if it "
        "survives your own skeptical review."
    ),
}

OUTPUT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "moex_agent_discovery",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "proposals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "direction": {"type": "string", "enum": DIRECTIONS},
                            "strategy": {"type": "string", "enum": STRATEGIES},
                            "d1_bar_end_utc": {"type": "string"},
                        },
                        "required": ["symbol", "direction", "strategy", "d1_bar_end_utc"],
                        "additionalProperties": False,
                    },
                },
                "forecast_reviews": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "direction": {"type": "string", "enum": DIRECTIONS},
                            "strategy": {"type": "string", "enum": STRATEGIES},
                            "d1_bar_end_utc": {"type": "string"},
                            "horizon_sessions": {"type": "string", "enum": ["1", "5", "20"]},
                            "assessment": {"type": "string", "enum": FORECAST_ASSESSMENTS},
                            "rationale": {"type": "string"},
                        },
                        "required": ["symbol", "direction", "strategy", "d1_bar_end_utc", "horizon_sessions", "assessment", "rationale"],
                        "additionalProperties": False,
                    },
                },
                "strategy_hypotheses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "strategy": {"type": "string", "enum": STRATEGIES},
                            "direction": {"type": "string", "enum": DIRECTIONS},
                            "timeframe_config": {"type": "string", "enum": list(TIMEFRAME_CONFIGS)},
                            "hypothesis": {"type": "string"},
                            "research_question": {"type": "string"},
                        },
                        "required": ["strategy", "direction", "timeframe_config", "hypothesis", "research_question"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["proposals", "strategy_hypotheses", "forecast_reviews"],
            "additionalProperties": False,
        },
    },
}


def _compact_context(
    scan: dict[str, Any], registry: dict[str, Any],
    forecast_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if scan.get("status") != "READ_ONLY_LATEST_SIGNAL_SCAN":
        raise ValueError("Input must be a deterministic read-only latest-signal scan")
    if not isinstance(scan.get("signals"), list) or not isinstance(scan.get("universe"), list):
        raise ValueError("Deterministic scan is missing signals or universe")
    summary = registry.get("summary") if isinstance(registry.get("summary"), dict) else {}
    coverage = registry.get("coverage")
    expected_symbols = len(scan["universe"])
    if (not isinstance(coverage, dict)
            or coverage.get("coverage_complete") is not True
            or coverage.get("expected_symbols") != expected_symbols
            or coverage.get("analyzed_symbols") != expected_symbols
            or coverage.get("unavailable_symbols") != 0
            or coverage.get("unexpected_result_tickers")):
        raise ValueError(
            "Strategy registry has missing or incomplete full-universe research coverage"
        )
    registry_rows = registry.get("strategies")
    if not isinstance(registry_rows, list):
        raise ValueError("Strategy registry has no strategies list")
    by_strategy_direction: dict[str, dict[str, int]] = defaultdict(lambda: {"PASS": 0, "REJECT": 0, "INSUFFICIENT_DATA": 0})
    for row in registry_rows:
        if not isinstance(row, dict):
            continue
        strategy = row.get("strategy")
        direction = row.get("direction")
        status = row.get("status")
        if strategy in STRATEGIES and direction in DIRECTIONS and status in {"PASS", "REJECT", "INSUFFICIENT_DATA"}:
            by_strategy_direction[f"{strategy}:{direction}"][status] += 1
    candidates = []
    for row in scan["signals"]:
        if not isinstance(row, dict):
            continue
        candidates.append({
            "symbol": row.get("symbol"),
            "direction": row.get("direction"),
            "strategy": row.get("strategy"),
            "d1_bar_end_utc": row.get("d1_bar_end_utc"),
            "h1_confirmation": row.get("h1_confirmation"),
            "cross_strategy_conflict": row.get("cross_strategy_conflict"),
        })
    forecast_context = None
    if forecast_report is not None:
        if (forecast_report.get("report_type") != "MOEX_EDGE_OPERATIONAL_DIRECTION_FORECAST_V1"
                or forecast_report.get("status") != "COMPLETE"):
            raise ValueError("Agents require a complete operational direction-forecast report")
        policy = forecast_report.get("holdout_policy") or {}
        if (policy.get("post_holdout_outcomes_used_for_training") != 0
                or policy.get("post_holdout_outcomes_used_for_model_selection") != 0
                or policy.get("post_holdout_outcomes_used_for_calibration") != 0
                or policy.get("post_holdout_outcomes_used_for_performance_metrics") != 0
                or policy.get("inference_parameters_frozen_before_holdout") is not True):
            raise ValueError("Forecast report violates the frozen holdout policy")
        forecast_rows = forecast_report.get("forecasts")
        if not isinstance(forecast_rows, list):
            raise ValueError("Forecast report is missing its forecast list")
        by_symbol: dict[str, dict[str, Any]] = defaultdict(dict)
        seen_forecasts = set()
        model_version = forecast_report.get("model_version")
        for row in forecast_rows:
            if not isinstance(row, dict):
                raise ValueError("Forecast row must be an object")
            ticker = row.get("ticker")
            horizon = row.get("horizon_sessions")
            key = (ticker, horizon)
            if ticker not in scan["universe"] or horizon not in (1, 5, 20) or key in seen_forecasts:
                raise ValueError("Forecast row has an invalid or duplicate ticker/horizon")
            if (row.get("status") != "EXPERIMENTAL_NOT_CALIBRATED"
                    or row.get("model_version") != model_version
                    or row.get("post_holdout_outcomes_used") is not False
                    or row.get("predicted_class") not in ("DOWN", "SIDEWAYS", "UP")):
                raise ValueError("Forecast row has an invalid model or holdout status")
            probabilities = {
                "DOWN": row.get("probability_down"),
                "SIDEWAYS": row.get("probability_sideways"),
                "UP": row.get("probability_up"),
            }
            values = list(probabilities.values())
            if (not all(isinstance(value, (int, float)) and math.isfinite(value)
                        and 0.0 <= value <= 1.0 for value in values)
                    or not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-8)):
                raise ValueError("Forecast probabilities must be finite, normalized and within [0, 1]")
            by_symbol[ticker][str(horizon)] = {
                "probabilities": probabilities,
                "predicted_class": row.get("predicted_class"),
                "calibration_status": "NOT_CALIBRATED",
                "status": row["status"],
            }
            seen_forecasts.add(key)
        expected = {(ticker, horizon) for ticker in scan["universe"] for horizon in (1, 5, 20)}
        if seen_forecasts != expected:
            raise ValueError("Forecast report must contain all 1/5/20-session forecasts for the full universe")

        # Validate the complete 44 x 3 forecast matrix above, but send only
        # forecasts relevant to current deterministic candidates to each agent.
        # This keeps free-tier prompts small without weakening full-universe checks.
        candidate_symbols = {
            row["symbol"] for row in candidates
            if row.get("symbol") in scan["universe"]
        }
        agent_forecasts = {
            symbol: by_symbol[symbol]
            for symbol in sorted(candidate_symbols)
            if symbol in by_symbol
        }
        forecast_context = {
            "model_version": model_version,
            "as_of_date": forecast_report.get("as_of_date"),
            "training_label_cutoff_exclusive": policy.get("holdout_start"),
            "calibration_status": "NOT_CALIBRATED",
            "full_universe_forecast_rows_validated": len(seen_forecasts),
            "candidate_symbols_shared_with_agents": len(agent_forecasts),
            "by_symbol": agent_forecasts,
        }

    return {
        "as_of_utc": scan.get("as_of_utc"),
        "universe": scan["universe"],
        "candidate_signals": candidates,
        "candidate_count": len(candidates),
        "direction_forecast": forecast_context,
        "strategy_registry_summary": summary,
        "strategy_evidence_by_family_and_direction": dict(by_strategy_direction),
        "allowed_strategy_families": STRATEGIES,
        "allowed_timeframe_configs": TIMEFRAME_CONFIGS,
        "important_limits": [
            "Only the exact candidate_signals listed here may be proposed as current signals.",
            "H1 confirmation is mandatory for a final confirmed signal.",
            "Strategy hypotheses are ideas only; they require deterministic historical testing.",
            "No raw OHLCV, future bars, broker data, account data or execution actions are available.",
            "Probabilities are read-only model output; do not alter, recalculate, or restate their numeric values.",
            "The probability model is NOT_CALIBRATED; never describe its probabilities as reliable or proven.",
            "You may identify qualitative agreement or disagreement with a candidate, but cannot change forecast classes or percentages.",
        ],
    }


def call_groq_discovery(
    prompt: str,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if not api_key or not api_key.strip():
        raise ValueError("GROQ_API_KEY is required")
    if not model or any(ch.isspace() for ch in model):
        raise ValueError("Invalid Groq model identifier")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": (
                "You are a read-only MOEX quantitative research agent. "
                "Do not fabricate market data, prices, performance, dates or signals. "
                "Use only the supplied deterministic snapshot."
            )},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_completion_tokens": 1536,
        "reasoning_format": "hidden",
        "reasoning_effort": "low",
        "response_format": OUTPUT_SCHEMA,
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "MOEX-EDGE-Research/1.0 (+https://github.com/vkazarin763-cloud/moex-edge-fast1)",
        },
        method="POST",
    )
    for attempt in range(3):
        try:
            with opener(request, timeout=50) as response:
                payload = json.loads(response.read().decode("utf-8"))
            choices = payload.get("choices") or []
            content = choices[0].get("message", {}).get("content") if choices else None
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("Groq discovery response contained no JSON message content")
            result = json.loads(content)
            if not isinstance(result, dict) or not {"proposals", "strategy_hypotheses"}.issubset(result) or set(result) - {"proposals", "strategy_hypotheses", "forecast_reviews"}:
                raise RuntimeError("Groq discovery response does not match the required outer schema")
            result.setdefault("forecast_reviews", [])
            if not all(isinstance(result[key], list) for key in ("proposals", "strategy_hypotheses", "forecast_reviews")):
                raise RuntimeError("Groq discovery response arrays are malformed")
            return result
        except json.JSONDecodeError as exc:
            if attempt < 2:
                sleeper(1)
                continue
            raise RuntimeError(
                "Agent provider returned truncated or invalid JSON after 3 attempts"
            ) from None
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                retry = 2 ** attempt
                try:
                    retry = min(60, max(1, int(float(exc.headers.get("Retry-After", retry)))))
                except (TypeError, ValueError, AttributeError):
                    pass
                sleeper(retry)
                continue
            detail = ""
            error_code = ""
            error_type = ""
            try:
                raw_body = exc.read().decode("utf-8", errors="replace").strip()
                payload = json.loads(raw_body) if raw_body else {}
                error = payload.get("error", {}) if isinstance(payload, dict) else {}
                if isinstance(error, dict):
                    detail = str(error.get("message") or payload.get("message") or "")
                    error_code = str(error.get("code") or "")
                    error_type = str(error.get("type") or "")
                elif isinstance(error, str):
                    detail = error
                elif isinstance(payload, dict):
                    detail = str(payload.get("message") or "")
                if not detail and raw_body and not raw_body.lstrip().startswith("<"):
                    detail = raw_body[:300]
            except (ValueError, OSError, AttributeError):
                pass
            # Never include request headers or credentials in diagnostics.
            detail = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", detail)[:400]
            suffix = f" [type={error_type}, code={error_code}]" if error_type or error_code else ""
            raise RuntimeError(
                f"Groq discovery API HTTP {exc.code}{suffix}: {detail or 'provider returned no readable error detail'}"
            ) from None
        except urllib.error.URLError:
            raise RuntimeError("Groq discovery API connection failed") from None
    raise RuntimeError("Groq discovery API rate-limit retries exhausted")


def call_openrouter_discovery(
    prompt: str,
    *,
    api_key: str,
    model: str = DEFAULT_OPENROUTER_MODEL,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if not api_key or not api_key.strip():
        raise ValueError("OPENROUTER_API_KEY is required")
    if not model or any(ch.isspace() for ch in model):
        raise ValueError("Invalid OpenRouter model identifier")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": (
                "You are a read-only MOEX quantitative research agent. "
                "Do not fabricate market data, prices, performance, dates or signals. "
                "Use only the supplied deterministic snapshot."
            )},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_completion_tokens": 6144,
        "response_format": OUTPUT_SCHEMA,
    }
    request = urllib.request.Request(
        OPENROUTER_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    for attempt in range(3):
        try:
            with opener(request, timeout=50) as response:
                payload = json.loads(response.read().decode("utf-8"))
            choices = payload.get("choices") or []
            content = choices[0].get("message", {}).get("content") if choices else None
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("OpenRouter discovery response contained no JSON message content")
            result = json.loads(content)
            if not isinstance(result, dict) or not {"proposals", "strategy_hypotheses"}.issubset(result) or set(result) - {"proposals", "strategy_hypotheses", "forecast_reviews"}:
                raise RuntimeError("OpenRouter discovery response does not match the required outer schema")
            result.setdefault("forecast_reviews", [])
            if not all(isinstance(result[key], list) for key in ("proposals", "strategy_hypotheses", "forecast_reviews")):
                raise RuntimeError("OpenRouter discovery response arrays are malformed")
            return result
        except json.JSONDecodeError as exc:
            if attempt < 2:
                sleeper(1)
                continue
            raise RuntimeError(
                "Agent provider returned truncated or invalid JSON after 3 attempts"
            ) from None
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                retry = 2 ** attempt
                try:
                    retry = min(60, max(1, int(float(exc.headers.get("Retry-After", retry)))))
                except (TypeError, ValueError, AttributeError):
                    pass
                sleeper(retry)
                continue
            detail = ""
            error_code = ""
            error_type = ""
            try:
                raw_body = exc.read().decode("utf-8", errors="replace").strip()
                payload = json.loads(raw_body) if raw_body else {}
                error = payload.get("error", {}) if isinstance(payload, dict) else {}
                if isinstance(error, dict):
                    detail = str(error.get("message") or payload.get("message") or "")
                    error_code = str(error.get("code") or "")
                    error_type = str(error.get("type") or "")
                elif isinstance(error, str):
                    detail = error
                elif isinstance(payload, dict):
                    detail = str(payload.get("message") or "")
                if not detail and raw_body and not raw_body.lstrip().startswith("<"):
                    detail = raw_body[:300]
            except (ValueError, OSError, AttributeError):
                pass
            # Never include request headers or credentials in diagnostics.
            detail = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", detail)[:400]
            suffix = f" [type={error_type}, code={error_code}]" if error_type or error_code else ""
            raise RuntimeError(
                f"OpenRouter discovery API HTTP {exc.code}{suffix}: {detail or 'provider returned no readable error detail'}"
            ) from None
        except urllib.error.URLError:
            raise RuntimeError("OpenRouter discovery API connection failed") from None
    raise RuntimeError("OpenRouter discovery API rate-limit retries exhausted")


def call_discovery_with_fallback(
    prompt: str,
    *,
    openrouter_api_key: str = "",
    groq_api_key: str = "",
    model: str = DEFAULT_OPENROUTER_MODEL,
    groq_model: str = DEFAULT_MODEL,
    openrouter_caller: Callable[..., dict[str, Any]] = call_openrouter_discovery,
    groq_caller: Callable[..., dict[str, Any]] = call_groq_discovery,
) -> tuple[dict[str, Any], str]:
    """Try OpenRouter first, then Groq; retain both sanitized failure reasons."""
    errors = []
    if openrouter_api_key.strip():
        try:
            return openrouter_caller(prompt, api_key=openrouter_api_key, model=model), "openrouter"
        except Exception as exc:
            errors.append(f"OpenRouter: {str(exc)[:500]}")
    else:
        errors.append("OpenRouter: OPENROUTER_API_KEY is not configured")
    if groq_api_key.strip():
        try:
            return groq_caller(prompt, api_key=groq_api_key, model=groq_model), "groq_fallback"
        except Exception as exc:
            errors.append(f"Groq: {str(exc)[:500]}")
    else:
        errors.append("Groq fallback: GROQ_API_KEY is not configured")
    raise RuntimeError("All configured AI providers failed. " + " | ".join(errors))


def _forecast_review_conflicts(
    reviews: list[dict[str, Any]], *, assessment_field: str = "assessment"
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, int], dict[str, list[str]]] = defaultdict(
        lambda: {"AGREES": [], "CONTRADICTS": [], "NEUTRAL": [], "INSUFFICIENT_EVIDENCE": []}
    )
    for review in reviews:
        assessment = review.get(assessment_field)
        if assessment not in FORECAST_ASSESSMENTS:
            continue
        key = (review["symbol"], review["direction"], review["strategy"],
               review["d1_bar_end_utc"], review["horizon_sessions"])
        grouped[key][assessment].append(review["role"])
    conflicts = []
    for key, roles in sorted(grouped.items()):
        if roles["AGREES"] and roles["CONTRADICTS"]:
            symbol, direction, strategy, d1_end, horizon = key
            conflicts.append({
                "symbol": symbol, "direction": direction, "strategy": strategy,
                "d1_bar_end_utc": d1_end, "horizon_sessions": horizon,
                "status": "CONTRADICTION",
                "agreeing_roles": sorted(roles["AGREES"]),
                "contradicting_roles": sorted(roles["CONTRADICTS"]),
            })
    return conflicts


def run_discovery(
    scan: dict[str, Any],
    registry: dict[str, Any],
    *,
    api_key: str = "",
    model: str = DEFAULT_OPENROUTER_MODEL,
    openrouter_api_key: str = "",
    groq_api_key: str = "",
    groq_model: str = DEFAULT_MODEL,
    caller: Callable[..., dict[str, Any]] = call_groq_discovery,
    forecast_report: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    context = _compact_context(scan, registry, forecast_report)
    forecast_context = context.get("direction_forecast")
    context_json = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    candidate_keys = {
        (row["symbol"], row["direction"], row["strategy"], row["d1_bar_end_utc"])
        for row in context["candidate_signals"]
        if all(row.get(key) is not None for key in ("symbol", "direction", "strategy", "d1_bar_end_utc"))
    }
    outputs = {}
    invalid_counts = {}
    providers_used = []
    proposal_votes: Counter = Counter()
    hypothesis_votes: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    hypothesis_rejections: dict[str, Counter] = defaultdict(Counter)
    forecast_reviews: list[dict[str, Any]] = []
    forecast_symbols = set(forecast_context.get("by_symbol", {})) if forecast_context else set()

    for role, instruction in ROLES.items():
        seen_proposals_this_agent = set()
        seen_hypotheses_this_agent = set()
        seen_forecast_reviews_this_agent = set()
        prompt = (
            f"ROLE: {role}. {instruction}\n"
            "Return the required JSON object. Proposals must copy an exact candidate row's "
            "symbol, direction, strategy and d1_bar_end_utc. Do not return price or indicator claims. "
            "Every proposal must use D1 and H1 (the final verifier enforces both). "
            "Each role must independently assess whether a listed frozen strategy/timeframe "
            "configuration merits a falsifiable research test. Return only independently "
            "supported hypotheses; an empty list is valid. Do not echo another role. "
            "A hypothesis is unverified, not a signal or a claim of profitability; consensus "
            "still requires support from at least two distinct roles. "
            "If direction_forecast is present, return forecast_reviews only for the first "
            "two candidate_signals in the supplied list (or fewer if fewer exist), covering "
            "horizons 1, 5 and 20 for each reviewed candidate. Copy the exact symbol, direction, "
            "strategy and d1_bar_end_utc. Compare candidate direction to predicted_class: LONG/UP "
            "or SHORT/DOWN is AGREES; LONG/DOWN or SHORT/UP is CONTRADICTS; SIDEWAYS is NEUTRAL; "
            "use INSUFFICIENT_EVIDENCE when the data do not support a view. This review limit does "
            "not limit signal proposals: consider every candidate_signal for proposals. Treat "
            "probabilities as experimental and NOT_CALIBRATED. Do not alter, recalculate or repeat "
            "numeric probabilities. If no candidate exists, return an empty forecast_reviews array.\n"
            f"DETERMINISTIC SNAPSHOT: {context_json}"
        )
        if caller is call_groq_discovery:
            response, provider_used = call_discovery_with_fallback(
                prompt,
                openrouter_api_key=openrouter_api_key,
                groq_api_key=groq_api_key or api_key,
                model=model,
                groq_model=groq_model,
            )
        else:
            response = caller(prompt, api_key=api_key, model=model)
            provider_used = "custom_test_caller"
        providers_used.append(provider_used)
        accepted = []
        invalid = 0
        for review in response.get("forecast_reviews", []):
            if not isinstance(review, dict):
                continue
            symbol = review.get("symbol")
            direction = review.get("direction")
            strategy = review.get("strategy")
            d1_bar_end_utc = review.get("d1_bar_end_utc")
            raw_horizon = review.get("horizon_sessions")
            try:
                horizon = int(raw_horizon) if str(raw_horizon) in {"1", "5", "20"} else None
            except (TypeError, ValueError):
                horizon = None
            reported_assessment = review.get("assessment")
            rationale = review.get("rationale")
            candidate_key = (symbol, direction, strategy, d1_bar_end_utc)
            review_key = (*candidate_key, horizon)
            forecast_row = (
                forecast_context.get("by_symbol", {}).get(symbol, {}).get(str(horizon), {})
                if forecast_context is not None else {}
            )
            predicted_class = forecast_row.get("predicted_class")
            expected_assessment = {
                ("LONG", "UP"): "AGREES",
                ("SHORT", "DOWN"): "AGREES",
                ("LONG", "DOWN"): "CONTRADICTS",
                ("SHORT", "UP"): "CONTRADICTS",
                ("LONG", "SIDEWAYS"): "NEUTRAL",
                ("SHORT", "SIDEWAYS"): "NEUTRAL",
            }.get((direction, predicted_class))
            if (forecast_context is not None and candidate_key in candidate_keys
                    and symbol in forecast_symbols and horizon in (1, 5, 20)
                    and direction in DIRECTIONS and expected_assessment is not None
                    and reported_assessment in FORECAST_ASSESSMENTS
                    and isinstance(rationale, str) and 0 < len(rationale.strip()) <= 400
                    and review_key not in seen_forecast_reviews_this_agent):
                seen_forecast_reviews_this_agent.add(review_key)
                rationale_by_class = {
                    "AGREES": f"Класс модели {predicted_class} согласуется с направлением {direction}.",
                    "CONTRADICTS": f"Класс модели {predicted_class} противоречит направлению {direction}.",
                    "NEUTRAL": "Класс SIDEWAYS не подтверждает ни LONG, ни SHORT.",
                }
                forecast_reviews.append({
                    "role": role, "symbol": symbol, "direction": direction,
                    "strategy": strategy, "d1_bar_end_utc": d1_bar_end_utc,
                    "horizon_sessions": horizon, "assessment": expected_assessment,
                    "agent_reported_assessment": reported_assessment,
                    "assessment_corrected": reported_assessment != expected_assessment,
                    "predicted_class": predicted_class,
                    "agent_rationale": rationale.strip(),
                    "rationale": rationale_by_class[expected_assessment],
                })
        for item in response["proposals"]:
            if not isinstance(item, dict):
                invalid += 1
                continue
            key = (item.get("symbol"), item.get("direction"), item.get("strategy"), item.get("d1_bar_end_utc"))
            if (key in candidate_keys
                    and all(isinstance(item.get(field), str) for field in ("symbol", "direction", "strategy", "d1_bar_end_utc"))
                    and key not in seen_proposals_this_agent):
                proposal_votes[key] += 1
                seen_proposals_this_agent.add(key)
                accepted.append(key)
            else:
                invalid += 1
        for idea in response["strategy_hypotheses"]:
            if not isinstance(idea, dict):
                hypothesis_rejections[role]["malformed_item"] += 1
                continue
            key = (idea.get("strategy"), idea.get("direction"), idea.get("timeframe_config"))
            if key[0] not in STRATEGIES or key[1] not in DIRECTIONS or key[2] not in TIMEFRAME_CONFIGS:
                hypothesis_rejections[role]["unsupported_configuration"] += 1
                continue
            if (not isinstance(idea.get("hypothesis"), str)
                    or not isinstance(idea.get("research_question"), str)
                    or not idea.get("hypothesis", "").strip()
                    or not idea.get("research_question", "").strip()):
                hypothesis_rejections[role]["missing_text"] += 1
                continue
            if re.search(r"\d", idea["hypothesis"] + idea["research_question"]):
                hypothesis_rejections[role]["numeric_claim"] += 1
                continue
            if key in seen_hypotheses_this_agent:
                hypothesis_rejections[role]["duplicate_from_same_agent"] += 1
                continue
            hypothesis_votes[key].append({"role": role, **idea})
            seen_hypotheses_this_agent.add(key)
        outputs[role] = {
            "proposals_returned": len(response["proposals"]),
            "exact_candidates_selected": len(accepted),
            "invalid_or_unmatched_proposals": invalid,
            "strategy_hypotheses_returned": len(response["strategy_hypotheses"]),
            "accepted_hypotheses": len(seen_hypotheses_this_agent),
            "hypothesis_rejections": dict(hypothesis_rejections[role]),
            "forecast_reviews_returned": len(response.get("forecast_reviews", [])),
        }
        invalid_counts[role] = invalid

    consensus = []
    for key, votes in proposal_votes.items():
        if votes >= 2:
            source = next(
                row for row in scan["signals"]
                if (row.get("symbol"), row.get("direction"), row.get("strategy"), row.get("d1_bar_end_utc")) == key
            )
            consensus.append({
                "symbol": key[0], "direction": key[1], "strategy": key[2],
                "d1_bar_end_utc": key[3], "timeframes": ["D1", "H1"],
                "rationale": "Selected independently by at least two research agents; source details are copied from the deterministic scan.",
                "agent_votes": votes,
            })
    consensus.sort(key=lambda row: (row["symbol"], row["direction"], row["strategy"]))

    hypothesis_candidates = []
    for key, ideas in hypothesis_votes.items():
        supporting_agents = sorted({idea["role"] for idea in ideas})
        hypothesis_candidates.append({
            "strategy": key[0], "direction": key[1], "timeframe_config": key[2],
            "timeframes": TIMEFRAME_CONFIGS[key[2]],
            "agent_votes": len(supporting_agents),
            "supporting_agents": supporting_agents,
            "hypothesis": ideas[0]["hypothesis"][:1000],
            "research_question": ideas[0]["research_question"][:1000],
            "status": (
                "UNTESTED_RESEARCH_HYPOTHESIS"
                if len(supporting_agents) >= 2
                else "INSUFFICIENT_INDEPENDENT_SUPPORT"
            ),
        })
    hypothesis_candidates.sort(key=lambda row: (row["strategy"], row["direction"], row["timeframe_config"]))
    hypotheses = [
        row for row in hypothesis_candidates
        if row["status"] == "UNTESTED_RESEARCH_HYPOTHESIS"
    ]

    report = {
        "status": "AGENT_SIGNAL_PROPOSALS",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "agent_run_id": os.getenv("GITHUB_RUN_ID", f"manual-{int(time.time())}"),
        "proposals": consensus,
        "forecast_reviews": forecast_reviews,
    }
    provider_set = set(providers_used)
    actual_provider = (
        "groq" if provider_set == {"groq_fallback"}
        else "openrouter" if provider_set == {"openrouter"}
        else "mixed" if provider_set
        else "none"
    )
    diagnostics = {
        "status": "AGENT_DISCOVERY_COMPLETE",
        "provider": actual_provider,
        "model": groq_model if provider_set == {"groq_fallback"} else model,
        "providers_used": providers_used,
        "agent_count": len(ROLES),
        "agent_roles": outputs,
        "candidate_count_seen": len(candidate_keys),
        "forecast_model_version": (forecast_context.get("model_version") if forecast_context else None),
        "forecast_as_of_date": (forecast_context.get("as_of_date") if forecast_context else None),
        "full_universe_forecast_rows_validated": (
            forecast_context.get("full_universe_forecast_rows_validated") if forecast_context else 0
        ),
        "forecast_symbols_shared_with_agents": (
            forecast_context.get("candidate_symbols_shared_with_agents") if forecast_context else 0
        ),
        "agents_can_modify_probabilities": False,
        "forecast_reviews_count": len(forecast_reviews),
        "forecast_review_conflicts": _forecast_review_conflicts(forecast_reviews),
        "forecast_review_agent_reported_conflicts": _forecast_review_conflicts(
            forecast_reviews, assessment_field="agent_reported_assessment"
        ),
        "forecast_review_corrections_count": sum(
            row["assessment_corrected"] for row in forecast_reviews
        ),
        "forecast_review_corrections_by_role": dict(Counter(
            row["role"] for row in forecast_reviews if row["assessment_corrected"]
        )),
        "consensus_proposal_count": len(consensus),
        "strategy_hypotheses": hypotheses,
        "hypothesis_candidates": hypothesis_candidates,
        "hypothesis_candidates_seen": len(hypothesis_candidates),
        "hypotheses_without_consensus_count": sum(
            row["status"] == "INSUFFICIENT_INDEPENDENT_SUPPORT"
            for row in hypothesis_candidates
        ),
        "hypothesis_count": len(hypotheses),
        "unmatched_or_invalid_proposals": invalid_counts,
        "policy": {
            "agents_are_proposers_only": True,
            "signal_candidates_must_match_deterministic_scan": True,
            "two_of_three_agent_consensus_required": True,
            "strategy_hypotheses_are_unverified": True,
            "new_strategy_formulas_are_not_yet_supported": True,
            "live_trading_authorized": False,
        },
    }
    return report, diagnostics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run free-tier autonomous MOEX strategy/signal discovery agents")
    parser.add_argument("--scan", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--forecast", default=None,
                        help="Optional complete operational forecast report; agents may critique but never alter probabilities")
    parser.add_argument("--proposals", default="agent_proposals.json")
    parser.add_argument("--diagnostics", default="agent_discovery_diagnostics.json")
    parser.add_argument("--verification", default="agent_signal_verification.json")
    parser.add_argument("--model", default=os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL))
    parser.add_argument("--groq-model", default=os.getenv("GROQ_MODEL", DEFAULT_MODEL))
    args = parser.parse_args(argv)
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
    groq_api_key = os.getenv("GROQ_API_KEY", "")
    scan = json.loads(Path(args.scan).read_text(encoding="utf-8"))
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    forecast_report = (
        json.loads(Path(args.forecast).read_text(encoding="utf-8"))
        if args.forecast else None
    )
    report, diagnostics = run_discovery(
        scan, registry, model=args.model,
        forecast_report=forecast_report,
        openrouter_api_key=openrouter_api_key, groq_api_key=groq_api_key,
        groq_model=args.groq_model,
    )
    verified = verify_agent_proposals(report, scan, registry)
    Path(args.proposals).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.diagnostics).write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.verification).write_text(json.dumps(verified, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Agent discovery complete: {diagnostics['agent_count']} agents; "
        f"{diagnostics['candidate_count_seen']} candidates; "
        f"{diagnostics['consensus_proposal_count']} consensus proposals; "
        f"{diagnostics['hypothesis_count']} untested research hypotheses."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
