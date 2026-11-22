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
    "dates, metrics or citations. If evidence is absent, say UNKNOWN. This is research "
    "commentary, not a trade instruction. Never recommend broker actions."
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
        "You are the systematic-strategy research analyst. Compare only the "
        "pre-registered strategy results and validation fields present in the report. "
        "Highlight sample size, costs, stability, out-of-sample status and caveats. "
        "Do not propose fitted parameters or claim profitability without evidence.",
    ),
    (
        "skeptical_reviewer",
        "You are an independent skeptical reviewer. Look for leakage, stale or "
        "incomplete data, multiple-testing risks, weak samples, contradictory fields "
        "and unsupported conclusions. Distinguish verified facts from hypotheses.",
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


def _compact_report(report: Any) -> str:
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
        if strategy_rows:
            row["w"] = strategy_rows
        compact_results[ticker] = row

    compact = {
        "generated_at_utc": report.get("generated_at_utc"),
        "source": _bounded(report.get("source")),
        "board": report.get("board"),
        "interval_minutes": report.get("interval_minutes"),
        "date_range": [report.get("date_from"), report.get("date_till")],
        "universe": _bounded(report.get("universe")),
        "development_holdout_policy": _bounded(report.get("development_holdout_policy", {})),
        "independent_validation": _bounded(report.get("independent_validation", {})),
        "results": compact_results,
        "schema": {
            "ticker_fields": {
                "s": "ticker status code",
                "b": "research input bars (fallback: candle count)",
                "q": "[data-quality status code, out-of-range bars, calendar-gap candidates, exchange calendar verified, session-date mapping complete]",
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
            "All ticker statuses, compact data-quality checks and per-strategy status/trade-count/"
            "average-net-return metrics are retained where present. Decode status codes using schema."
        ),
    }
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_INPUT_CHARS:
        raise ValueError(
            f"Compacted research summary is {len(encoded)} characters; "
            f"limit is {MAX_INPUT_CHARS}. Reduce report metadata before AI review."
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
        detail = ""
        try:
            error_payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            error_obj = error_payload.get("error", {}) if isinstance(error_payload, dict) else {}
            if isinstance(error_obj, dict):
                message = error_obj.get("message")
                if isinstance(message, str):
                    detail = " ".join(message.split())[:400]
        except (ValueError, OSError):
            pass
        if detail:
            detail = detail.replace(api_key, "[REDACTED]")
            raise RuntimeError(f"{provider} API HTTP {exc.code}: {detail}") from None
        raise RuntimeError(
            f"{provider} API HTTP {exc.code}; provider returned no readable error message."
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
    api_key: str,
    model: str = DEFAULT_MODEL,
    provider: str = DEFAULT_PROVIDER,
    groq_api_key: str | None = None,
    groq_model: str = DEFAULT_GROQ_MODEL,
    caller: Callable[..., str] = call_provider,
) -> dict[str, Any]:
    """Run three specialists and a coordinator; four calls total with per-call fallback."""
    report_json = _compact_report(report)
    specialist_results: dict[str, str] = {}
    providers_used: list[str] = []

    def ask(prompt: str) -> str:
        try:
            answer = caller(prompt, api_key=api_key, provider=provider, model=model)
            providers_used.append(provider)
            return answer
        except Exception as primary_error:
            if provider == "openrouter" and groq_api_key and groq_api_key.strip():
                answer = caller(
                    prompt, api_key=groq_api_key, provider="groq", model=groq_model
                )
                providers_used.append("groq_fallback")
                return answer
            raise RuntimeError(
                f"Primary provider {provider} failed; no configured fallback. "
                f"Details: {primary_error}"
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
        "The supplied deterministic report is the sole quantitative source.\n\n"
        f"Validated report (JSON):\n{report_json}\n\n"
        "Specialist notes:\n"
        + "\n\n".join(f"[{name}]\n{note}" for name, note in specialist_results.items())
    )
    synthesis = ask(coordinator_prompt)
    return {
        "status": "AI_COMMENTARY_ONLY",
        "provider": provider,
        "providers_used": providers_used,
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
    parser.add_argument("--input", required=True, help="Path to a compact validated research JSON report.")
    parser.add_argument("--output", required=True, help="Path for the AI commentary JSON output.")
    parser.add_argument("--provider", default=os.getenv("AI_PROVIDER", DEFAULT_PROVIDER))
    parser.add_argument("--model", default=os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL))
    parser.add_argument("--groq-model", default=os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL))
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
    result = run_team(
        report,
        api_key=api_key,
        model=args.model,
        provider=args.provider,
        groq_api_key=os.getenv("GROQ_API_KEY"),
        groq_model=args.groq_model,
    )
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote read-only AI commentary to {args.output}; providers={','.join(result['providers_used'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
