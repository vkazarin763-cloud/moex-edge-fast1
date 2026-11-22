# Optional free Gemini research team

The existing `research_agent` is the deterministic MOEX research and validation
pipeline. This optional LLM layer adds commentary; it does not replace calculations,
data-quality checks, walk-forward validation, the prospective holdout, or human review.

## Provider

- Google Gemini Developer API, default model: `gemini-3.8-flash`.
- The model is listed with free-tier input/output pricing by Google. Actual RPM/TPM/RPD
  quotas are project-specific and may change; check Google AI Studio before use.
- Free-tier prompts and responses may be used by Google to improve its products.
  Do not send broker credentials, account data, personal information, or confidential data.
- The runner makes four sequential model calls: market analyst, strategy researcher,
  skeptical reviewer, then coordinator. It is manual-only and does not schedule itself.

Create a key at https://aistudio.google.com/ and store it locally in the environment
or as a GitHub Actions secret named `GEMINI_API_KEY`. Never commit the key, paste it
into code, or print it in logs.

## Run

First create a compact JSON file containing the already validated research summary.
Do not pass raw candle histories or account/portfolio data.

```bash
export GEMINI_API_KEY="..."
python -m research_agent.ai_team --input research_summary.json --output ai_commentary.json
```

Optional model override:

```bash
export GEMINI_MODEL="gemini-3.5-flash-lite"
```

The output is labelled `AI_COMMENTARY_ONLY`. It is not a signal, recommendation,
backtest, independent validation or permission to trade. There is no broker, order,
Telegram or production scanner integration. The layer is not called by any existing
scheduled workflow.

## Offline tests

```bash
python -m unittest tests.test_research_ai_team -v
```
