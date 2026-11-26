# MOEX EDGE — Fundamentals research agent (free-source MVP)

This module is independent of the Finam AI Screener, Finam credentials, broker
execution, Telegram, and production signal generation.

## What it does now

- Calls the public MOEX ISS corporate-information report-list endpoint and
  company-reference endpoint.
- Stores the source response rows and a normalized report index.
- Keeps the publication timestamp separate from the reporting-period end.
- Maps a report to a ticker only when the source explicitly supplies a security
  identifier. Unmatched rows are retained rather than guessed.
- Runs on weekdays through GitHub Actions and can also be started manually.

## Important source limitation

MOEX documents corporate-report metadata endpoints under CCI. However,
structured IFRS/RAS financial datasets and ready-made financial indicators are
described by MOEX as subscription services. This MVP does not assume those
datasets are free, does not bypass access controls, and records HTTP 401/403 or
missing blocks as source limitations. See:
- https://www.moex.com/a2836
- https://www.moex.com/tsentr-korporativnoj-informatsii
- https://www.moex.com/media/instruktsiya-po-ispolzovaniyu-servisov-tski.pdf

The first stage is report discovery, not yet a financial-statement parser.
It must not claim that a company is financially strong/weak until source
documents have been retrieved and key figures verified against the original
report. Missing figures remain null.

## Next research stages

1. Verify actual public API response blocks and ticker/company identifier
   coverage for the 44-symbol universe.
2. Add free primary-source document retrieval where issuers publish direct
   downloadable IFRS/RAS reports.
3. Parse PDF/XLSX only with page/sheet and source-document evidence retained.
4. Extract revenue, EBITDA, net profit, net debt, operating/free cash flow,
   margins, ROE/ROA and valuation only when explicitly available.
5. Store document publication time, report period, accounting standard,
   consolidated/standalone scope, currency, units, URL and content hash.
6. Build point-in-time fundamentals only after publication-date and
   restatement-version handling is reliable.

No historical backtest may use a report before its actual public release time.
Fundamental data is a slow-moving eligibility/context filter, not an H1 entry
timer. No production, live-order, Telegram, cron-job.org, or Finam settings are
changed by this module.
