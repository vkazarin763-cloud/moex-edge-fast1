# Optional Groq multi-agent research team

The existing `research_agent` remains the deterministic MOEX research and validation
pipeline. This optional LLM layer adds commentary only; it does not replace calculations,
data-quality checks, walk-forward validation, prospective holdout testing, or human review.

## Provider

- Provider: GroqCloud Chat Completions API (OpenAI-compatible).
- Default model: `openai/gpt-oss-20b`, listed in Groq's current supported-model catalogue.
- API endpoint: `https://api.groq.com/openai/v1/chat/completions`.
- Groq publishes Free-tier rate limits; exact limits depend on the account/organization
  and can change. Check the Limits page in GroqCloud before running. The current docs
  list `openai/gpt-oss-20b` with 30 RPM, 1,000 RPD, 8K TPM and 200K TPD as base
  limits; do not treat these as a guarantee for every account.
- The runner makes four sequential calls: market analyst, strategy researcher,
  skeptical reviewer, then coordinator. It is manual-only and has no schedule.

Create an API key in GroqCloud and store it as an environment variable named
`GROQ_API_KEY` locally or as a GitHub Actions repository secret. Never commit the
key, paste it into code, or print it in logs. Optional model override: `GROQ_MODEL`.

Do not send broker credentials, account data, personal information, or confidential data.

## Run

First create a compact JSON file containing the already validated research summary.
Do not pass raw candle histories or account/portfolio data.

```bash
export GROQ_API_KEY="..."
python -m research_agent.ai_team --input research_summary.json --output ai_commentary.json
```

Optional model override:

```bash
export GROQ_MODEL="openai/gpt-oss-120b"
```

The output is labelled `AI_COMMENTARY_ONLY`. It is not a signal, recommendation,
backtest, independent validation or permission to trade. There is no broker, order,
Telegram or production scanner integration. The layer is not called by any existing
scheduled workflow.

## Offline tests

```bash
python -m unittest tests.test_research_ai_team -v
```

Tests mock the HTTP response and do not use the API key or make a live request.
