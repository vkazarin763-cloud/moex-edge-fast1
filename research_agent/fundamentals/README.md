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
- Smart-Lab redirect URLs are unwrapped only when the redirect host is
  Smart-Lab and the destination is HTTPS. Candidate destinations are
  classified for known disclosure-operator (e-disclosure.ru) and regulator
  (cbr.ru) domains; this is domain classification, not proof that a page
  belongs to a specific issuer or contains a financial statement.
- The Yandex links found in the 2026-11-25 snapshot resolve to three
  e-disclosure.ru events describing changes in insider ownership rights.
  They are corporate disclosure events, not financial statements. The event
  pages could not be fetched by the collector/browser fetch service during
  verification, so page contents and issuer identity remain unverified.
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

## Primary financial-report sources and verification pipeline

Source priority (free access; no AI screener):
1. Issuer's own Investor Relations / Disclosure page (primary publisher).
2. Interfax e-disclosure company profile and attached documents (public access, accredited disclosure operator).
3. Smart-Lab Telegram/articles only as discovery leads; never primary evidence.
4. MOEX CCI metadata only if accessible without paid credentials; SSL validation stays enabled.

Interfax company search: https://www.e-disclosure.ru/poisk-po-kompaniyam . Search by issuer legal name, INN, OGRN, or issuer code, then confirm the profile ticker/issuer identity before opening reports. Its public pages describe access to issuer reports, consolidated financial statements, annual reports, and material-event disclosures without registration.

A candidate is accepted as a financial-report document only after verifying all fields: ticker and issuer legal name; source/profile URL; document URL; report type (IFRS/RAS); consolidated/standalone scope; reporting period; publication date; currency and units; audit/review status; document hash; retrieval timestamp. Corporate events (insider changes, dividends, board decisions) are separate event records and must not be mislabeled as financial statements. Missing fields are null, not inferred.

The first phase is discovery only: create a source lead and a manual/automated verification status. Numeric extraction and investment interpretation are deferred until source identity and document authenticity are verified. No paid API, AI Screener, broker, signal, or production workflow is involved.
