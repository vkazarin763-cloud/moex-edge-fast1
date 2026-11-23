"""One-shot, read-only provider connectivity diagnostic; no market data is used."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .ai_team import DEFAULT_GROQ_MODEL, DEFAULT_MODEL, call_provider


def main() -> int:
    prompt = (
        "Reply with exactly: PROVIDER_OK. This is a connectivity diagnostic, "
        "not a market analysis. Do not add any other text."
    )
    checks = []
    providers = (
        ("openrouter", os.getenv("OPENROUTER_API_KEY", ""), os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)),
        ("groq", os.getenv("GROQ_API_KEY", ""), os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)),
    )
    for provider, api_key, model in providers:
        item = {"provider": provider, "model": model}
        if not api_key.strip():
            item.update({"status": "NOT_CONFIGURED", "error": "API key secret is not configured"})
        else:
            try:
                answer = call_provider(
                    prompt,
                    api_key=api_key,
                    provider=provider,
                    model=model,
                    timeout=45,
                )
                item.update({
                    "status": "PASS" if "PROVIDER_OK" in answer else "RESPONDED_UNEXPECTEDLY",
                    "response_preview": " ".join(answer.split())[:240],
                })
            except Exception as exc:
                item.update({"status": "FAIL", "error": str(exc)[:700]})
        checks.append(item)
        print(f"{provider}: {item['status']}" + (f" — {item['error']}" if item.get("error") else ""))

    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "provider connectivity only; no MOEX data, research, signals, or broker access",
        "checks": checks,
    }
    Path("provider_diagnostic.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # A failed provider is diagnostic data, not a workflow infrastructure failure.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
