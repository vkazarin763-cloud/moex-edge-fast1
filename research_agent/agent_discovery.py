"""Free-tier Groq agents propose strategy ideas and shortlist deterministic MOEX signals.

The agents never calculate or authoritatively publish prices/signals. Every signal
proposal must be an exact member of the deterministic D1/H1 scan. Strategy ideas
are exploratory suggestions from the existing frozen strategy/timeframe catalog;
they are not backtest results or approvals.
"""
from __future__ import annotations

import argparse
import json
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
DEFAULT_MODEL = "openai/gpt-oss-20b"
STRATEGIES = ["Donchian20", "EMA20x50", "RSI14Trend50", "MACD12x26", "Keltner20x2ATR"]
DIRECTIONS = ["LONG", "SHORT"]
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
        "candidate_signals. Never invent a ticker, direction, strategy or D1 bar-end."
    ),
    "strategy_scout": (
        "Explore which existing frozen strategy families and timeframe configurations "
        "deserve the next deterministic research test. You may shortlist current signals "
        "only when an exact candidate row supports them. Do not invent performance."
    ),
    "skeptical_reviewer": (
        "Act as an adversarial reviewer. Reject weak, conflicting or poorly confirmed "
        "candidates. Prefer an empty shortlist over unsupported proposals. Highlight "
        "limitations in qualitative strategy hypotheses."
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
                            "rationale": {"type": "string"},
                        },
                        "required": ["symbol", "direction", "strategy", "d1_bar_end_utc", "rationale"],
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
            "required": ["proposals", "strategy_hypotheses"],
            "additionalProperties": False,
        },
    },
}


def _compact_context(scan: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    if scan.get("status") != "READ_ONLY_LATEST_SIGNAL_SCAN":
        raise ValueError("Input must be a deterministic read-only latest-signal scan")
    if not isinstance(scan.get("signals"), list) or not isinstance(scan.get("universe"), list):
        raise ValueError("Deterministic scan is missing signals or universe")
    summary = registry.get("summary") if isinstance(registry.get("summary"), dict) else {}
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
    return {
        "as_of_utc": scan.get("as_of_utc"),
        "universe": scan["universe"],
        "candidate_signals": candidates,
        "candidate_count": len(candidates),
        "strategy_registry_summary": summary,
        "strategy_evidence_by_family_and_direction": dict(by_strategy_direction),
        "allowed_strategy_families": STRATEGIES,
        "allowed_timeframe_configs": TIMEFRAME_CONFIGS,
        "important_limits": [
            "Only the exact candidate_signals listed here may be proposed as current signals.",
            "H1 confirmation is mandatory for a final confirmed signal.",
            "Strategy hypotheses are ideas only; they require deterministic historical testing.",
            "No raw OHLCV, future bars, broker data, account data or execution actions are available.",
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
        "max_completion_tokens": 1400,
        "response_format": OUTPUT_SCHEMA,
    }
    request = urllib.request.Request(
        API_URL,
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
                raise RuntimeError("Groq discovery response contained no JSON message content")
            result = json.loads(content)
            if not isinstance(result, dict) or set(result) != {"proposals", "strategy_hypotheses"}:
                raise RuntimeError("Groq discovery response does not match the required outer schema")
            if not isinstance(result["proposals"], list) or not isinstance(result["strategy_hypotheses"], list):
                raise RuntimeError("Groq discovery response arrays are malformed")
            return result
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
            try:
                error = json.loads(exc.read().decode("utf-8", errors="replace")).get("error", {})
                detail = str(error.get("message", ""))[:300] if isinstance(error, dict) else ""
            except (ValueError, OSError):
                pass
            raise RuntimeError(f"Groq discovery API HTTP {exc.code}: {detail or 'provider error'}") from None
        except urllib.error.URLError:
            raise RuntimeError("Groq discovery API connection failed") from None
    raise RuntimeError("Groq discovery API rate-limit retries exhausted")


def run_discovery(
    scan: dict[str, Any],
    registry: dict[str, Any],
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    caller: Callable[..., dict[str, Any]] = call_groq_discovery,
) -> tuple[dict[str, Any], dict[str, Any]]:
    context = _compact_context(scan, registry)
    context_json = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    candidate_keys = {
        (row["symbol"], row["direction"], row["strategy"], row["d1_bar_end_utc"])
        for row in context["candidate_signals"]
        if all(row.get(key) is not None for key in ("symbol", "direction", "strategy", "d1_bar_end_utc"))
    }
    outputs = {}
    invalid_counts = {}
    proposal_votes: Counter = Counter()
    hypothesis_votes: dict[tuple, list[dict[str, Any]]] = defaultdict(list)

    for role, instruction in ROLES.items():
        seen_proposals_this_agent = set()
        seen_hypotheses_this_agent = set()
        prompt = (
            f"ROLE: {role}. {instruction}\n"
            "Return the required JSON object. Proposals must copy an exact candidate row's "
            "symbol, direction, strategy and d1_bar_end_utc. Do not return price or indicator claims. "
            "Every proposal must use D1 and H1 (the final verifier enforces both). "
            "Strategy hypotheses may only select a listed frozen strategy and timeframe config; "
            "they are unverified research questions, not signals or claims of profitability. "
            "Do not propose a strategy family outside the supplied catalog.\n"
            f"DETERMINISTIC SNAPSHOT: {context_json}"
        )
        response = caller(prompt, api_key=api_key, model=model)
        accepted = []
        invalid = 0
        for item in response["proposals"]:
            if not isinstance(item, dict):
                invalid += 1
                continue
            key = (item.get("symbol"), item.get("direction"), item.get("strategy"), item.get("d1_bar_end_utc"))
            if (key in candidate_keys
                    and all(isinstance(item.get(field), str) for field in ("symbol", "direction", "strategy", "d1_bar_end_utc", "rationale"))
                    and key not in seen_proposals_this_agent):
                proposal_votes[key] += 1
                seen_proposals_this_agent.add(key)
                accepted.append(key)
            else:
                invalid += 1
        for idea in response["strategy_hypotheses"]:
            if not isinstance(idea, dict):
                continue
            key = (idea.get("strategy"), idea.get("direction"), idea.get("timeframe_config"))
            if (key[0] in STRATEGIES and key[1] in DIRECTIONS and key[2] in TIMEFRAME_CONFIGS
                    and isinstance(idea.get("hypothesis"), str)
                    and isinstance(idea.get("research_question"), str)
                    and not re.search(r"\d", idea.get("hypothesis", "") + idea.get("research_question", ""))
                    and key not in seen_hypotheses_this_agent):
                hypothesis_votes[key].append({"role": role, **idea})
                seen_hypotheses_this_agent.add(key)
        outputs[role] = {
            "proposals_returned": len(response["proposals"]),
            "exact_candidates_selected": len(accepted),
            "invalid_or_unmatched_proposals": invalid,
            "strategy_hypotheses_returned": len(response["strategy_hypotheses"]),
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

    hypotheses = []
    for key, ideas in hypothesis_votes.items():
        if len(ideas) >= 2:
            hypotheses.append({
                "strategy": key[0], "direction": key[1], "timeframe_config": key[2],
                "timeframes": TIMEFRAME_CONFIGS[key[2]],
                "agent_votes": len(ideas),
                "supporting_agents": sorted({idea["role"] for idea in ideas}),
                "hypothesis": ideas[0]["hypothesis"][:1000],
                "research_question": ideas[0]["research_question"][:1000],
                "status": "UNTESTED_RESEARCH_HYPOTHESIS",
            })
    hypotheses.sort(key=lambda row: (row["strategy"], row["direction"], row["timeframe_config"]))

    report = {
        "status": "AGENT_SIGNAL_PROPOSALS",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "agent_run_id": os.getenv("GITHUB_RUN_ID", f"manual-{int(time.time())}"),
        "proposals": consensus,
    }
    diagnostics = {
        "status": "AGENT_DISCOVERY_COMPLETE",
        "provider": "groq_api",
        "model": model,
        "agent_count": len(ROLES),
        "agent_roles": outputs,
        "candidate_count_seen": len(candidate_keys),
        "consensus_proposal_count": len(consensus),
        "strategy_hypotheses": hypotheses,
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
    parser.add_argument("--proposals", default="agent_proposals.json")
    parser.add_argument("--diagnostics", default="agent_discovery_diagnostics.json")
    parser.add_argument("--verification", default="agent_signal_verification.json")
    parser.add_argument("--model", default=os.getenv("GROQ_MODEL", DEFAULT_MODEL))
    args = parser.parse_args(argv)
    api_key = os.getenv("GROQ_API_KEY", "")
    scan = json.loads(Path(args.scan).read_text(encoding="utf-8"))
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    report, diagnostics = run_discovery(scan, registry, api_key=api_key, model=args.model)
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
