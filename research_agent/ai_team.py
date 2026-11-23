"""Optional, read-only multi-agent commentary over validated MOEX research JSON.

This module does not fetch market data, calculate indicators, place orders, or send alerts.
All quantitative facts must come from the supplied deterministic research report.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_PROVIDER = "openrouter"
DEFAULT_MODEL = "openrouter/free"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
MAX_INPUT_CHARS = 30_000
MAX_OUTPUT_TOKENS = 4_096

SYSTEM_PROMPT = (
    "You are part of a read-only MOEX research team. Never fabricate facts, prices, "
    "dates, metrics or citations. If evidence is absent, say UNKNOWN. The directional "
    "strategy_registry is the sole authority for per-ticker LONG/SHORT eligibility, "
    "status, trade counts, fold adequacy and shadow-scanner eligibility. Never promote "
    "an aggregate or legacy walk-forward result over the registry. If registry status "
    "is INSUFFICIENT_DATA, do not describe that candidate as passed, approved or eligible. "
    "Cross-sectional summaries are descriptive only, not selection decisions. The prospective ""Holm family covers ticker x frozen strategy hypotheses and does not split LONG/SHORT; ""the development registry does split directions, so never compare its row count directly ""with prospective holdout family_size. Follow explicit family_scope metadata. Report "
    "cost assumptions exactly as supplied; do not say they are undisclosed when present. "
    "Treat session_date_mapping and tqbr_history_crosscheck as data-quality evidence. "
    "Report volume-only mismatches and affected dates exactly; do not infer root cause or "
    "switch the model-input volume source without a validated policy. Weekend fragments "
    "are expected in the same-date crosscheck only when the report says all were mapped. "
    "This is research commentary, not a trade instruction. Never recommend broker actions."
)

ROLES: tuple[tuple[str, str], ...] = (
    (
        "market_analyst",
        "You are the MOEX market-context analyst. Identify market regime, breadth, "
        "concentration and data limitations visible in the supplied report. Do not "
        "invent current prices, news, catalysts or facts. Mark missing evidence UNKNOWN.",
    ),
    (
        "strategy_researcher",
        "You are the systematic-strategy research analyst. Use strategy_registry.strategies "
        "as the authoritative, direction-specific selection table. Report counts and status "
        "exactly. Cross-sectional summaries from the source report are descriptive diagnostics "
        "only and cannot override registry status. Highlight sample size, per-fold adequacy, "
        "baseline and doubled costs, holdout status and caveats. Do not propose fitted "
        "parameters or claim profitability without evidence.",
    ),
    (
        "skeptical_reviewer",
        "You are an independent skeptical reviewer. Look for leakage, stale or "
        "incomplete data, multiple-testing risks, weak samples, contradictory fields "
        "and unsupported conclusions. Cross-check every claimed pass against the directional "
        "strategy registry; flag any conflict and treat the registry as authoritative for "
        "eligibility. Distinguish verified facts from hypotheses.",
    ),
)


def _bounded(value: Any, *, depth: int = 0) -> Any:
    """Bound small metadata objects without retaining event/fold histories."""
    if depth > 7:
        return "[omitted: nesting limit]"
    if isinstance(value, dict):
        omitted = {
            "trade_ledger", "raw_candles", "raw_history", "history_records",
            "records", "ohlcv", "timestamps", "folds", "candidate_trades",
            "continuous_development_replay", "mark_to_market_portfolio",
            "equity_curve", "events", "calendar_gap_candidates",
        }
        return {
            key: _bounded(item, depth=depth + 1)
            for key, item in value.items()
            if str(key).lower() not in omitted
        }
    if isinstance(value, list):
        # Keep only tiny scalar metadata arrays; omit event/fold collections.
        if len(value) <= 4 and all(not isinstance(item, (dict, list)) for item in value):
            return value
        return "[omitted: detailed list]"
    if isinstance(value, str) and len(value) > 400:
        return value[:400] + "…[truncated]"
    return value


def _compact_report(report: Any, registry: Any = None) -> str:
    """Build a strict, compact evidence projection under the AI input budget."""
    if not isinstance(report, dict):
        raise ValueError("Research report must be a JSON object.")
    raw_results = report.get("results")
    if not isinstance(raw_results, dict):
        encoded = json.dumps(_bounded(report), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded) > MAX_INPUT_CHARS:
            raise ValueError("Focused research evidence exceeds the AI input budget.")
        return encoded

    # Compact codes avoid repeating long status strings across 44 tickers x strategies.
    status_codes: dict[str, str] = {}
    def status_code(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        if value not in status_codes:
            status_codes[value] = f"S{len(status_codes) + 1}"
        return status_codes[value]

    strategy_codes = {
        "Donchian20": "D20",
        "EMA20x50": "E2050",
        "Keltner20x2ATR": "K20",
        "MACD12x26": "M1226",
        "RSI14Trend50": "R14",
    }
    compact_results: dict[str, Any] = {}
    for ticker, result in sorted(raw_results.items()):
        if not isinstance(result, dict):
            compact_results[ticker] = {"s": status_code("MALFORMED_RESULT")}
            continue
        quality = result.get("data_quality")
        quality_row = None
        if isinstance(quality, dict):
            quality_row = [
                status_code(quality.get("status")),
                quality.get("out_of_range_bars"),
                quality.get("calendar_gap_count"),
                quality.get("exchange_calendar_verified"),
                quality.get("session_date_mapping_complete"),
            ]
        walk_forward = result.get("walk_forward")
        candidates = walk_forward.get("candidates") if isinstance(walk_forward, dict) else None
        strategy_rows = {}
        if isinstance(candidates, dict):
            for strategy, metrics in sorted(candidates.items()):
                if not isinstance(metrics, dict):
                    continue
                strategy_rows[strategy_codes.get(strategy, strategy)] = [
                    status_code(metrics.get("status")),
                    metrics.get("closed_trades"),
                    round(metrics["average_net_return"], 6)
                    if isinstance(metrics.get("average_net_return"), (int, float))
                    else None,
                ]
        row = {
            "s": status_code(result.get("status")),
            "b": result.get("research_input_bars", result.get("candles")),
        }
        if quality_row is not None:
            row["q"] = quality_row
        session_mapping = result.get("session_date_mapping")
        if isinstance(session_mapping, dict):
            row["m"] = {
                "s": status_code(session_mapping.get("status")),
                "trading_days_reconciled": session_mapping.get("trading_days_reconciled"),
                "trading_days_mismatched": session_mapping.get("trading_days_mismatched"),
                "mismatch_field_counts": _bounded(session_mapping.get("mismatch_field_counts", {})),
                "mismatch_examples": [
                    _bounded(item) for item in session_mapping.get("mismatch_examples", [])[:3]
                    if isinstance(item, dict)
                ] if isinstance(session_mapping.get("mismatch_examples"), list) else [],
                "unassigned_raw_candles": session_mapping.get("unassigned_raw_candles"),
                "raw_history_coverage_status": session_mapping.get("raw_history_coverage_status"),
                "raw_history_date_coverage_ratio": session_mapping.get("raw_history_date_coverage_ratio"),
            }
        history_crosscheck = result.get("tqbr_history_crosscheck")
        if isinstance(history_crosscheck, dict):
            row["h"] = {
                "s": status_code(history_crosscheck.get("status")),
                "missing_candles_on_trade_dates": len(history_crosscheck.get("missing_candles_on_trade_dates", []))
                if isinstance(history_crosscheck.get("missing_candles_on_trade_dates"), list) else None,
                "zero_trade_sessions_without_candles": len(history_crosscheck.get("zero_trade_sessions_without_candles", []))
                if isinstance(history_crosscheck.get("zero_trade_sessions_without_candles"), list) else None,
                "candles_present_on_zero_trade_dates": len(history_crosscheck.get("candles_present_on_zero_trade_dates", []))
                if isinstance(history_crosscheck.get("candles_present_on_zero_trade_dates"), list) else None,
                "history_rows_unknown_trade_count": len(history_crosscheck.get("history_rows_unknown_trade_count", []))
                if isinstance(history_crosscheck.get("history_rows_unknown_trade_count"), list) else None,
                "candles_without_history_record": len(history_crosscheck.get("candles_without_history_record", []))
                if isinstance(history_crosscheck.get("candles_without_history_record"), list) else None,
                "mapped_weekend_fragments_without_same_date_history": history_crosscheck.get(
                    "mapped_weekend_fragments_without_same_date_history"
                ),
                "weekend_fragments_excluded_from_same_date_crosscheck": history_crosscheck.get(
                    "weekend_fragments_excluded_from_same_date_crosscheck"
                ),
                "mapped_weekday_additional_session_fragments_without_same_date_history": history_crosscheck.get(
                    "mapped_weekday_additional_session_fragments_without_same_date_history"
                ),
                "weekday_additional_session_fragments_excluded_from_same_date_crosscheck": history_crosscheck.get(
                    "weekday_additional_session_fragments_excluded_from_same_date_crosscheck"
                ),
            }
        if strategy_rows:
            row["w"] = strategy_rows
        compact_results[ticker] = row

    compact_registry = None
    if registry is not None:
        if not isinstance(registry, dict) or not isinstance(registry.get("strategies"), list):
            raise ValueError("Strategy registry must contain a strategies list.")
        compact_registry = {
            "registry_version": registry.get("registry_version"),
            "stage": registry.get("stage"),
            "source_report_generated_at_utc": registry.get("source_report_generated_at_utc"),
            "source_report_date_till": registry.get("source_report_date_till"),
            "holdout_start": registry.get("holdout_start"),
            "holdout_used_for_selection": registry.get("holdout_used_for_selection"),
            "selection_policy": _bounded(registry.get("selection_policy", {})),
            "summary": _bounded(registry.get("summary", {})),
            "scanner_contract": _bounded(registry.get("scanner_contract", {})),
            "strategies": [
                {
                    "ticker": item.get("ticker"),
                    "direction": item.get("direction"),
                    "strategy": item.get("strategy"),
                    "status": item.get("status"),
                    "reasons": _bounded(item.get("reasons", [])),
                    "closed_trades": item.get("closed_trades"),
                    "average_net_return": item.get("average_net_return"),
                    "profit_factor": item.get("profit_factor"),
                    "positive_folds": item.get("positive_folds"),
                    "adequately_sampled_folds": item.get("adequately_sampled_folds"),
                    "folds": item.get("folds"),
                    "double_cost_average_net_return": item.get("double_cost_average_net_return"),
                    "eligible_for_shadow_scanner": item.get("eligible_for_shadow_scanner"),
                }
                for item in registry["strategies"]
                if isinstance(item, dict)
            ],
            "authority_note": (
                "This direction-specific registry is authoritative for selection and "
                "scanner eligibility. Never infer a PASS from source-report aggregates."
            ),
        }

    compact_costs = {}
    for ticker, result in sorted(raw_results.items()):
        if not isinstance(result, dict):
            continue
        adversarial = result.get("adversarial_cost_check")
        if isinstance(adversarial, dict):
            compact_costs[ticker] = {
                "stress": adversarial.get("stress"),
                "baseline_execution_config": _bounded(adversarial.get("baseline_execution_config", {})),
                "double_cost_execution_config": _bounded(adversarial.get("double_cost_execution_config", {})),
            }

    compact = {
        "generated_at_utc": report.get("generated_at_utc"),
        "source": _bounded(report.get("source")),
        "board": report.get("board"),
        "interval_minutes": report.get("interval_minutes"),
        "date_range": [report.get("date_from"), report.get("date_till")],
        "universe": _bounded(report.get("universe")),
        "development_holdout_policy": _bounded(report.get("development_holdout_policy", {})),
        "multiple_testing_scope_note": (
            "The Holm family applies only to prospective holdout hypotheses: one per "
            "ticker x frozen entry strategy; prospective holdout does not split LONG/SHORT. "
            "The separate development registry does split LONG/SHORT. Do not compare "
            "Holm family_size directly with the development registry row count."
        ),
        "independent_validation": _bounded(report.get("independent_validation", {})),
        "cost_model_by_ticker": compact_costs,
        "strategy_registry": compact_registry,
        "results": compact_results,
        "schema": {
            "ticker_fields": {
                "s": "ticker status code",
                "b": "research input bars (fallback: candle count)",
                "q": "[data-quality status code, out-of-range bars, calendar-gap candidates, exchange calendar verified, session-date mapping complete]",
                "m": "raw session reconciliation status, matched/mismatched days, field counts/examples, unassigned count and date coverage",
                "h": "TQBR history crosscheck status and counts, including weekend fragments excluded only after complete session mapping",
                "w": "walk-forward candidates keyed by strategy code; each value is [status code, closed trades, average net return]",
            },
            "strategy_codes": {value: key for key, value in strategy_codes.items()},
            "status_codes": {code: value for value, code in status_codes.items()},
        },
        "cross_sectional_direction_summary": _bounded(
            report.get("cross_sectional_direction_summary", {})
        ),
        "experiment_lab": _bounded(report.get("experiment_lab", {})),
        "safety": _bounded(report.get("safety", {})),
        "compaction_note": (
            "Raw OHLCV, detailed folds, trade ledgers and development portfolio replay are excluded. "
            "All ticker statuses, compact data-quality checks, session-reconciliation evidence, "
            "TQBR history crosscheck counts and per-strategy status/trade-count/average-net-return "
            "metrics are retained where present. Decode status codes using schema. "
            "The directional strategy_registry, when supplied, is authoritative for eligibility. "
            "Per-ticker baseline and doubled-cost execution assumptions are included where present."
        ),
    }
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # Preserve decision-critical evidence (all ticker rows, all directional registry
    # rows, costs and audit status). If the prompt is still too large, progressively
    # reduce descriptive metadata rather than failing the entire AI commentary run.
    if len(encoded) > MAX_INPUT_CHARS and "experiment_lab" in compact:
        lab = compact["experiment_lab"]
        lab_status = lab.get("status") if isinstance(lab, dict) else None
        compact["experiment_lab"] = {
            "status": lab_status,
            "detail": "Detailed experiment-lab metadata omitted to fit the AI input budget."
        }
        encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_INPUT_CHARS and "cross_sectional_direction_summary" in compact:
        compact["cross_sectional_direction_summary"] = {
            "detail": "Descriptive cross-sectional breakdown omitted to fit the AI input budget; "
                      "direction-specific registry remains authoritative."
        }
        encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_INPUT_CHARS:
        # Keep the audit outcome and counts, but drop verbose warning payloads.
        audit = compact.get("independent_validation")
        if isinstance(audit, dict):
            compact["independent_validation"] = {
                key: audit.get(key)
                for key in ("status", "checks", "errors", "warnings_count")
                if key in audit
            }
            if "warnings_count" not in compact["independent_validation"] and isinstance(audit.get("warnings"), list):
                compact["independent_validation"]["warnings_count"] = len(audit["warnings"])
            encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_INPUT_CHARS:
        raise ValueError(
            f"Decision-critical research evidence is {len(encoded)} characters; "
            f"limit is {MAX_INPUT_CHARS}. Core registry and ticker evidence were not truncated."
        )
    return encoded

def _extract_text(response: dict[str, Any], provider: str = "AI provider") -> str:
    """Extract user-facing text and report safe metadata for empty generations."""
    if not isinstance(response, dict):
        raise RuntimeError(f"{provider} returned a malformed response object.")
    api_error = response.get("error")
    if isinstance(api_error, dict):
        code = api_error.get("code", "unknown")
        message = api_error.get("message")
        detail = " ".join(message.split())[:300] if isinstance(message, str) else "no error message"
        raise RuntimeError(f"{provider} returned API error {code}: {detail}")

    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError(f"{provider} returned no choices (possibly blocked, unavailable, or quota-limited).")
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        result = content.strip()
    elif isinstance(content, list):
        result = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
        ).strip()
    else:
        result = ""

    if not result:
        finish = choice.get("finish_reason") or "unknown"
        native_finish = choice.get("native_finish_reason") or "unknown"
        usage = response.get("usage") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        reasoning_tokens = completion_details.get("reasoning_tokens", "unknown")
        generation_id = response.get("id") or "unavailable"
        raise RuntimeError(
            f"{provider} returned empty content (finish_reason={finish}, "
            f"native_finish_reason={native_finish}, reasoning_tokens={reasoning_tokens}, "
            f"generation_id={generation_id})."
        )
    return result


def call_provider(
    prompt: str,
    *,
    api_key: str,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    timeout: int = 60,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    """Call an OpenAI-compatible provider without extra dependencies."""
    providers = {
        "openrouter": OPENROUTER_API_URL,
        "groq": GROQ_API_URL,
    }
    if provider not in providers:
        raise ValueError("Unsupported AI provider. Use 'openrouter' or 'groq'.")
    if not api_key.strip():
        raise ValueError(f"{provider.upper()}_API_KEY is required.")
    if not model.strip() or any(ch.isspace() for ch in model):
        raise ValueError(f"Invalid {provider} model identifier.")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": MAX_OUTPUT_TOKENS,
    }
    if provider == "groq":
        body["max_completion_tokens"] = body.pop("max_tokens")
    else:
        # Free-model routing can select reasoning models; keep reasoning bounded
        # so the entire output budget is not consumed before user-facing text.
        body["reasoning"] = {"effort": "low", "exclude": True}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/vkazarin763-cloud/moex-edge-fast1"
        headers["X-OpenRouter-Title"] = "MOEX EDGE Research Team"
    request = urllib.request.Request(
        providers[provider],
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Preserve a short, sanitized provider response even when it is not JSON.
        # Request IDs are useful for provider support and are not credentials.
        raw_detail = ""
        try:
            raw_detail = exc.read().decode("utf-8", errors="replace")
        except OSError:
            pass
        detail = ""
        try:
            error_payload = json.loads(raw_detail)
            error_obj = error_payload.get("error", {}) if isinstance(error_payload, dict) else {}
            if isinstance(error_obj, dict):
                message = error_obj.get("message")
                if isinstance(message, str):
                    detail = " ".join(message.split())
        except ValueError:
            detail = " ".join(raw_detail.split())
        detail = detail.replace(api_key, "[REDACTED]")[:400]
        request_id = ""
        if exc.headers:
            request_id = (
                exc.headers.get("x-request-id")
                or exc.headers.get("request-id")
                or exc.headers.get("cf-ray")
                or ""
            )
        suffix = f"; request_id={request_id[:120]}" if request_id else ""
        if detail:
            raise RuntimeError(
                f"{provider} API HTTP {exc.code}: {detail}{suffix}"
            ) from None
        raise RuntimeError(
            f"{provider} API HTTP {exc.code}: empty response body{suffix}"
        ) from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{provider} API connection failed: {exc.reason}") from None
    return _extract_text(payload, provider)


def call_groq(
    prompt: str,
    *,
    api_key: str,
    model: str = DEFAULT_GROQ_MODEL,
    timeout: int = 60,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    """Backward-compatible Groq call, used as the secondary provider."""
    return call_provider(
        prompt, api_key=api_key, provider="groq", model=model,
        timeout=timeout, opener=opener,
    )

def run_team(
    report: Any,
    *,
    registry: Any = None,
    api_key: str,
    model: str = DEFAULT_MODEL,
    provider: str = DEFAULT_PROVIDER,
    groq_api_key: str | None = None,
    groq_model: str = DEFAULT_GROQ_MODEL,
    fallback_model: str | None = None,
    caller: Callable[..., str] = call_provider,
) -> dict[str, Any]:
    """Run three specialists and a coordinator; four calls total with per-call fallback."""
    report_json = _compact_report(report, registry=registry)
    specialist_results: dict[str, str] = {}
    providers_used: list[str] = []
    provider_diagnostics: list[dict[str, str]] = []

    def ask(prompt: str) -> str:
        try:
            answer = caller(prompt, api_key=api_key, provider=provider, model=model)
            providers_used.append(provider)
            return answer
        except Exception as primary_error:
            primary_detail = str(primary_error)[:600]
            # Prefer a second free model on the same OpenRouter endpoint. This
            # tests model-level resilience, not independent-provider resilience.
            if provider == "openrouter" and fallback_model and fallback_model != model:
                try:
                    answer = caller(
                        prompt, api_key=api_key, provider="openrouter", model=fallback_model
                    )
                except Exception as fallback_error:
                    fallback_detail = str(fallback_error)[:600]
                    provider_diagnostics.append({
                        "primary_provider": provider,
                        "primary_model": model,
                        "primary_error": primary_detail,
                        "fallback_provider": "openrouter",
                        "fallback_model": fallback_model,
                        "fallback_error": fallback_detail,
                    })
                    if groq_api_key and groq_api_key.strip():
                        try:
                            answer = caller(
                                prompt, api_key=groq_api_key, provider="groq", model=groq_model
                            )
                        except Exception as groq_error:
                            raise RuntimeError(
                                f"Primary OpenRouter model failed: {primary_detail}; "
                                f"OpenRouter fallback model failed: {fallback_detail}; "
                                f"Groq fallback failed: {str(groq_error)[:600]}"
                            ) from None
                        providers_used.append("groq_fallback")
                        return answer
                    raise RuntimeError(
                        f"Primary OpenRouter model failed: {primary_detail}; "
                        f"OpenRouter fallback model failed: {fallback_detail}"
                    ) from None
                provider_diagnostics.append({
                    "primary_provider": provider,
                    "primary_model": model,
                    "primary_error": primary_detail,
                    "fallback_provider": "openrouter",
                    "fallback_model": fallback_model,
                    "fallback_status": "SUCCEEDED",
                })
                providers_used.append("openrouter_model_fallback")
                return answer
            if provider == "openrouter" and groq_api_key and groq_api_key.strip():
                try:
                    answer = caller(
                        prompt, api_key=groq_api_key, provider="groq", model=groq_model
                    )
                except Exception as fallback_error:
                    fallback_detail = str(fallback_error)[:600]
                    provider_diagnostics.append({
                        "primary_provider": provider,
                        "primary_error": primary_detail,
                        "fallback_provider": "groq",
                        "fallback_error": fallback_detail,
                    })
                    raise RuntimeError(
                        f"Primary provider {provider} failed: {primary_detail}; "
                        f"fallback provider groq failed: {fallback_detail}"
                    ) from None
                provider_diagnostics.append({
                    "primary_provider": provider,
                    "primary_error": primary_detail,
                    "fallback_provider": "groq",
                    "fallback_status": "SUCCEEDED",
                })
                providers_used.append("groq_fallback")
                return answer
            raise RuntimeError(
                f"Primary provider {provider} failed; no configured fallback. "
                f"Details: {primary_detail}"
            ) from None

    for role, instruction in ROLES:
        specialist_results[role] = ask(
            f"{instruction}\n\nValidated research report (JSON):\n{report_json}"
        )

    coordinator_prompt = (
        "You are the lead coordinator of a MOEX research team. Reconcile the three "
        "independent notes below. Return a concise report with: verified facts, "
        "disagreements, unresolved questions, data-quality caveats, and next research "
        "checks. Never invent evidence or turn commentary into a trading signal. "
        "The supplied deterministic report is the sole quantitative source. The directional "
        "strategy_registry inside it is authoritative for all candidate statuses and "
        "scanner eligibility; source-report cross-sectional summaries must never override it. "
        "Explicitly identify any legacy aggregate that conflicts with the registry. Do not "
        "mislabel the different prospective-holdout and directional-development hypothesis "
        "families as a multiple-testing discrepancy; use the supplied family_scope metadata.\n\n"
        f"Validated report (JSON):\n{report_json}\n\n"
        "Specialist notes:\n"
        + "\n\n".join(f"[{name}]\n{note}" for name, note in specialist_results.items())
    )
    synthesis = ask(coordinator_prompt)
    return {
        "status": "AI_COMMENTARY_ONLY",
        "registry_included": registry is not None,
        "registry_summary": _bounded(registry.get("summary", {})) if isinstance(registry, dict) else None,
        "provider": provider,
        "providers_used": providers_used,
        "provider_diagnostics": provider_diagnostics,
        "model": model,
        "calls": len(ROLES) + 1,
        "specialists": specialist_results,
        "coordinator": synthesis,
        "limitations": [
            "LLM commentary is not a calculation, backtest, independent validation or trade signal.",
            "Quantitative claims must be checked against the source report.",
            "No broker, account, order, Telegram or production-scanner integration exists.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run optional read-only multi-provider AI commentary on a validated JSON report."
    )
    parser.add_argument("--input", required=True, help="Path to a validated research JSON report.")
    parser.add_argument("--registry", default="", help="Path to the direction-specific strategy registry JSON.")
    parser.add_argument("--output", required=True, help="Path for the AI commentary JSON output.")
    parser.add_argument("--provider", default=os.getenv("AI_PROVIDER", DEFAULT_PROVIDER))
    parser.add_argument("--model", default=os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL))
    parser.add_argument("--groq-model", default=os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL))
    parser.add_argument("--fallback-model", default=os.getenv("OPENROUTER_BACKUP_MODEL", ""))
    args = parser.parse_args(argv)

    if args.provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            parser.error("Set OPENROUTER_API_KEY in GitHub Actions secrets.")
    elif args.provider == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            parser.error("Set GROQ_API_KEY in GitHub Actions secrets.")
    else:
        parser.error("AI_PROVIDER must be 'openrouter' or 'groq'.")

    report = json.loads(Path(args.input).read_text(encoding="utf-8"))
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8")) if args.registry else None
    if args.registry and not isinstance(registry.get("strategies"), list):
        parser.error("The supplied strategy registry has no strategies list.")
    result = run_team(
        report,
        registry=registry,
        api_key=api_key,
        model=args.model,
        provider=args.provider,
        groq_api_key=os.getenv("GROQ_API_KEY"),
        groq_model=args.groq_model,
        fallback_model=args.fallback_model or None,
    )
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote read-only AI commentary to {args.output}; providers={','.join(result['providers_used'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
