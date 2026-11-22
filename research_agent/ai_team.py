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

API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-20b"
MAX_INPUT_CHARS = 30_000
MAX_OUTPUT_TOKENS = 1_200

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
    """Remove bulky audit ledgers/raw series while retaining bounded evidence."""
    if depth > 8:
        return "[omitted: nesting limit]"
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in {
                "trade_ledger", "raw_candles", "raw_history",
                "history_records", "records", "ohlcv", "timestamps",
            }:
                continue
            if normalized == "candles" and isinstance(item, (list, dict)):
                continue
            cleaned[key] = _bounded(item, depth=depth + 1)
        return cleaned
    if isinstance(value, list):
        # Fold summaries and small diagnostics remain useful; raw event lists do not.
        return [_bounded(item, depth=depth + 1) for item in value[:12]]
    if isinstance(value, str) and len(value) > 600:
        return value[:600] + "…[truncated]"
    return value


def _compact_report(report: Any) -> str:
    """Build a deterministic evidence-only summary; never send raw candle history."""
    if not isinstance(report, dict):
        raise ValueError("Research report must be a JSON object.")
    raw_results = report.get("results")
    if not isinstance(raw_results, dict):
        # Small structured evidence objects are supported for focused agent reviews/tests.
        encoded = json.dumps(_bounded(report), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded) > MAX_INPUT_CHARS:
            raise ValueError("Focused research evidence exceeds the Groq input budget.")
        return encoded

    ticker_fields = (
        "status", "error", "candles", "raw_session_candles",
        "research_input_bars", "development_bars", "first_timestamp",
        "last_timestamp", "data_quality", "raw_candle_quality",
        "corporate_action_history_basis", "tqbr_history_crosscheck",
        "walk_forward", "adversarial_cost_check", "prospective_holdout",
    )
    compact_results = {}
    for ticker, result in sorted(raw_results.items()):
        if not isinstance(result, dict):
            compact_results[ticker] = {"status": "MALFORMED_RESULT"}
            continue
        compact_results[ticker] = _bounded({
            key: result[key] for key in ticker_fields if key in result
        })

    compact = {
        "generated_at_utc": report.get("generated_at_utc"),
        "source": report.get("source"),
        "board": report.get("board"),
        "interval_minutes": report.get("interval_minutes"),
        "date_from": report.get("date_from"),
        "date_till": report.get("date_till"),
        "universe": report.get("universe"),
        "development_holdout_policy": _bounded(report.get("development_holdout_policy", {})),
        "independent_validation": _bounded(report.get("independent_validation", {})),
        "results": compact_results,
        "cross_sectional_direction_summary": _bounded(
            report.get("cross_sectional_direction_summary", {})
        ),
        "experiment_lab": _bounded(report.get("experiment_lab", {})),
        "development_portfolio": _bounded(report.get("development_portfolio", {})),
        "safety": report.get("safety"),
        "compaction_note": (
            "Raw OHLCV/candle arrays and per-trade ledgers are intentionally excluded. "
            "All retained metrics are copied from the deterministic source report."
        ),
    }
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_INPUT_CHARS:
        # Last-resort smaller view: preserve status, errors, validation and aggregate metrics.
        compact["results"] = {
            ticker: {
                key: value for key, value in item.items()
                if key in {"status", "error", "candles", "research_input_bars",
                           "first_timestamp", "last_timestamp"}
            }
            for ticker, item in compact_results.items()
        }
        compact["cross_sectional_direction_summary"] = _bounded(
            report.get("cross_sectional_direction_summary", {})
        )
        encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_INPUT_CHARS:
        raise ValueError(
            f"Compacted research summary is {len(encoded)} characters; "
            f"limit is {MAX_INPUT_CHARS}. Reduce report metadata before AI review."
        )
    return encoded

def _extract_text(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError("Groq returned no choices (possibly blocked or quota-limited).")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        result = content.strip()
    elif isinstance(content, list):
        result = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
    else:
        result = ""
    if not result:
        raise RuntimeError("Groq response contained no text.")
    return result


def call_groq(
    prompt: str,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout: int = 60,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    """Call Groq's OpenAI-compatible Chat Completions API without extra dependencies."""
    if not api_key.strip():
        raise ValueError("GROQ_API_KEY is required.")
    if not model.strip() or any(ch.isspace() for ch in model):
        raise ValueError("Invalid Groq model identifier.")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_completion_tokens": MAX_OUTPUT_TOKENS,
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Never include response bodies or request headers in logs.
        raise RuntimeError(f"Groq API HTTP {exc.code}. Check the key, model and account limits.") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Groq API connection failed: {exc.reason}") from None
    return _extract_text(payload)


def run_team(
    report: Any,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    caller: Callable[..., str] = call_groq,
) -> dict[str, Any]:
    """Run three specialist agents and a coordinator; four model calls total."""
    report_json = _compact_report(report)
    specialist_results: dict[str, str] = {}
    for role, instruction in ROLES:
        specialist_results[role] = caller(
            f"{instruction}\n\nValidated research report (JSON):\n{report_json}",
            api_key=api_key,
            model=model,
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
    synthesis = caller(coordinator_prompt, api_key=api_key, model=model)
    return {
        "status": "AI_COMMENTARY_ONLY",
        "provider": "groq_api",
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
        description="Run optional read-only Groq research commentary on a validated JSON report."
    )
    parser.add_argument("--input", required=True, help="Path to a compact validated research JSON report.")
    parser.add_argument("--output", required=True, help="Path for the AI commentary JSON output.")
    parser.add_argument("--model", default=os.getenv("GROQ_MODEL", DEFAULT_MODEL))
    args = parser.parse_args(argv)

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        parser.error("Set GROQ_API_KEY in the process environment; never put it in a file or command line.")

    report = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = run_team(report, api_key=api_key, model=args.model)
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote read-only AI commentary to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
