"""Optional, read-only multi-agent commentary over validated MOEX research JSON.

This module does not fetch market data, calculate indicators, place orders, or send alerts.
All quantitative facts must come from the supplied deterministic research report.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.8-flash"
MAX_INPUT_CHARS = 30_000
MAX_OUTPUT_TOKENS = 1_200

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


def _compact_report(report: Any) -> str:
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_INPUT_CHARS:
        raise ValueError(
            f"Research input is {len(encoded)} characters; limit is {MAX_INPUT_CHARS}. "
            "Pass a compact validated summary, not raw candle history."
        )
    return encoded


def _extract_text(response: dict[str, Any]) -> str:
    candidates = response.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates (possibly blocked or quota-limited).")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    if not text.strip():
        raise RuntimeError("Gemini response contained no text.")
    return text.strip()


def call_gemini(
    prompt: str,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout: int = 60,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    """Call Gemini generateContent without third-party dependencies."""
    if not api_key.strip():
        raise ValueError("GEMINI_API_KEY is required.")
    if not model or "/" in model or ":" in model:
        raise ValueError("Invalid Gemini model identifier.")
    url = f"{API_BASE}/{model}:generateContent"
    body = {
        "systemInstruction": {
            "parts": [{
                "text": (
                    "You are part of a read-only MOEX research team. "
                    "Never provide fabricated facts, prices, dates, metrics or citations. "
                    "If evidence is absent, say UNKNOWN. This is research commentary, "
                    "not a trade instruction. Never recommend broker actions."
                )
            }]
        },
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "responseMimeType": "text/plain",
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Do not expose request headers or credentials in logs.
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        raise RuntimeError(f"Gemini API HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Gemini API connection failed: {exc.reason}") from None
    return _extract_text(payload)


def run_team(
    report: Any,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    caller: Callable[..., str] = call_gemini,
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
        "provider": "google_gemini_api",
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
        description="Run optional read-only Gemini research commentary on a validated JSON report."
    )
    parser.add_argument("--input", required=True, help="Path to a compact validated research JSON report.")
    parser.add_argument("--output", required=True, help="Path for the AI commentary JSON output.")
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
    args = parser.parse_args(argv)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        parser.error("Set GEMINI_API_KEY in the process environment; never put it in a file or command line.")

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
