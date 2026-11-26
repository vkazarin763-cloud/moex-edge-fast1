# MOEX EDGE — Fundamentals research agent (free-source MVP)

The module is research-only and read-only. It does not use Finam AI Screener,
broker execution, live signals, or production settings.

## Smart-Lab Telegram discovery

- Public channel: https://t.me/newssmartlab
- Collector: `python -m research_agent.fundamentals.smartlab_collector`
- Reads the public Telegram preview, paginates up to five pages, deduplicates
  posts, and matches explicit ticker tags/tokens from the 44-stock universe.
- Classifies report, revenue/profit, dividend, debt, and guidance topics.
- Follows public Smart-Lab article links from ticker-matched posts and records
  article title/description plus external links that look like possible
  issuer documents (e.g. report/disclosure/PDF links).
- A candidate URL is only a lead. The system does not assume that an external
  link is an issuer primary source; issuer domain and document authenticity
  still require verification.
- Each Telegram item is marked `unverified_news_lead`. Article pages are
  marked `article_not_primary_source`.
- Telegram's preview is a recent, best-effort slice, not a complete archive.

## MOEX CCI metadata

The separate MOEX CCI collector checks company/report metadata endpoints.
Structured financial data access may be restricted. SSL verification remains
enabled; certificate errors are recorded, never bypassed.

## Data integrity

Before financial figures are extracted, preserve the issuer document URL,
actual publication timestamp, reporting period, IFRS/RAS standard,
consolidated/standalone scope, currency, units, and content hash. Never use
period-end date as a substitute for publication time. Missing values remain
null; no headline is treated as a financial statement. Preserve restatements
and document versions before any point-in-time backtest.

## Workflow and safety

GitHub Actions validates changes and can be started manually; no scheduled
polling is enabled. Snapshots are stored on
`research/price-forecast-24h-v1`.

No production signals, live orders, Telegram notification bot, secrets,
cron-job.org schedule, Finam settings, or production repository are changed.
