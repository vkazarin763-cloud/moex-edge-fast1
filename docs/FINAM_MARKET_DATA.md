# Finam AI Screener adapter (read-only)

## Scope and separation

This is a separate adapter for structured responses returned by the user's
authenticated Finam MCP session. It does not open a network connection,
authenticate, access accounts, create alerts or presets, or submit orders.

The repository already contains `research_agent/finam_market_data.py`, a
separate read-only Finam Trade API historical-candle client. This screener
adapter does not replace or modify that client. It is also not imported by the
frozen signal scanner and does not modify the frozen strategy cohort, formulas,
holdout, or execution paths.

## Frozen universe and request flow

The adapter contains the 44 tickers from `v1-frozen-2026-11-19` and the Finam
security IDs resolved through read-only `search_securities` calls and then
used in successful `screen_securities(ids=...)` calls.

Call `build_screener_requests()`. It returns five deterministic argument
objects with 10, 10, 10, 10, and 4 IDs. Pass each object as the arguments to
the Finam MCP `screen_securities` tool. Do not replace the ID list with a
market-wide query. The requested metrics are `quote_last`,
`market_capitalization`, `pe_ratio`, and `dividend_yield_12m`.

Pass the five structured JSON responses to
`normalize_screener_responses(responses, retrieved_at=...)`. The timestamp
must be the caller's actual timezone-aware retrieval time (UTC recommended),
not a guessed market timestamp.

## Export-to-snapshot bridge

The interactive Copilot MCP session and GitHub Actions are separate execution
environments. The repository therefore does not pretend it can call tools from
the user's Copilot session. Instead, after the authenticated MCP session has
returned the five responses, export them into a JSON file with this envelope:

```json
{
  "retrieved_at": "2026-11-22T12:34:56Z",
  "responses": [
    { "data": [], "has_next": false },
    { "data": [], "has_next": false },
    { "data": [], "has_next": false },
    { "data": [], "has_next": false },
    { "data": [], "has_next": false }
  ]
}
```

Replace the illustrative empty `data` arrays with the complete raw MCP
responses. `retrieved_at` must be the actual timezone-aware time when those
responses were obtained; do not use the later file-import time or a chart
candle timestamp. The importer requires exactly five responses, validates all
44 symbols, rejects incomplete pagination and refuses to overwrite an existing
snapshot unless explicitly passed `--force`.

Run:

```bash
python scripts/import_finam_screener_snapshot.py --input /path/to/finam_export.json --output data/research/finam_screener_44.json
```

The resulting JSON is a research snapshot only. Its quote freshness remains
`UNKNOWN` because the provider response did not include a verified quote
timestamp. Do not feed this snapshot into the production scanner or trading
executor.

## Data contract

- Returned `security_id`, ticker, and market ID must agree with the frozen map.
- Duplicate rows, unknown IDs, extra symbols, missing symbols, malformed
  values, non-finite numbers, and invalid prices/capitalizations fail closed.
- Provider nulls remain null; they are never imputed.
- Dividend yield is preserved as the source fraction and also exposed as
  percentage points (fraction × 100). For example, 0.1345 becomes 13.45.
- Retrieval time is not quote time. Until Finam supplies a verified quote
  timestamp, each row has `quote_timestamp_utc: null` and
  `quote_freshness: UNKNOWN_NO_PROVIDER_QUOTE_TIMESTAMP`.
- Minute-chart candle timestamps are not substituted for last-trade or
  quote-update timestamps.
- The normalized top-level freshness state remains `UNKNOWN`.

## Tests

Run from the repository root:

```bash
python -m unittest discover -s tests -p "test_finam_screener_adapter.py" -v
```

Tests use synthetic fixtures only. They validate mapping, batching, schema,
normalization, and fail-closed behavior; they do not establish live data
availability, freshness, or strategy profitability.

Snapshot importer tests:

```bash
python -m unittest discover -s tests -p "test_finam_screener_snapshot_import.py" -v
```

## GitHub Actions intake (no Finam credentials in CI)

The repository includes `.github/workflows/finam-screener-snapshot-intake.yml`.
It runs only when a JSON export is pushed under
`data/research/finam_screener_exports/`. It validates each export with the
same fail-closed importer and publishes normalized JSON as a downloadable
Actions artifact (14-day retention).

The workflow does **not** connect to Finam or perform MCP authentication.
Finam's documented connection flow requires the user's Finam ID and token and
an interactive `Authenticate` step in the MCP client. Keep those credentials
out of GitHub Actions until Finam documents a supported non-interactive
machine-to-machine flow. Never commit credentials or broker account data.

To use the intake bridge:
1. Retrieve the five `screen_securities` responses through an authenticated
   Finam MCP client.
2. Save the raw response envelope (with the actual timezone-aware
   `retrieved_at`) as a JSON file under
   `data/research/finam_screener_exports/`.
3. Commit and push that file to this branch.
4. Download the `finam-screener-normalized-snapshots` artifact from the
   resulting Actions run. Its quote freshness remains UNKNOWN unless the
   provider supplies a verified quote timestamp.

This is a read-only research intake. It does not update scanner signals,
strategies, the sealed holdout, or any trading/execution component.
