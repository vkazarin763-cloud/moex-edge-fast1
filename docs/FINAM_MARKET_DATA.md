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
python -m unittest tests.test_finam_screener_adapter -v
```

Tests use synthetic fixtures only. They validate mapping, batching, schema,
normalization, and fail-closed behavior; they do not establish live data
availability, freshness, or strategy profitability.
