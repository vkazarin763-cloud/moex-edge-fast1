# OpenRouter setup for the MOEX research team

The manual AI research workflow uses OpenRouter as its primary OpenAI-compatible provider. If an OpenRouter request fails, the same agent call is retried through Groq when `GROQ_API_KEY` is configured.

## One-time setup

1. Create an API key at https://openrouter.ai/keys.
2. Set a spending limit on the key. Do not create an unrestricted key.
3. In this repository, open **Settings → Secrets and variables → Actions**.
4. Add a repository secret named `OPENROUTER_API_KEY` and paste the key there. Never put the key in source code, workflow inputs, or chat.
5. Keep the existing `GROQ_API_KEY` secret if you want Groq fallback.

## Run

Open **Actions → Manual AI Research Team → Run workflow**. The default model is `openrouter/free`, which routes to an available free model. Free-model availability and rate limits can vary. If needed, select a specific model ID from https://openrouter.ai/models; verify its current price and availability before running.

The workflow makes three specialist calls and one coordinator call. It does not place orders, send Telegram alerts, access brokerage accounts, or modify the production scanner.

## Secrets and data

- `OPENROUTER_API_KEY`: required primary provider key.
- `GROQ_API_KEY`: optional fallback provider key.
- Keys are passed to the workflow as environment variables and are never printed.
- The compacted research summary is sent to the selected model provider. Review OpenRouter and the selected model provider's data policies before use.
- Source report and commentary are uploaded as a GitHub Actions artifact.
