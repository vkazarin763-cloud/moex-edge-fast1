# MOEX EDGE — Fundamentals research agent (free-source MVP)

This module is isolated from production trading, Finam AI Screener, broker
execution, and live signal generation. All collectors are read-only.

## Current sources

### Smart-Lab Telegram news — discovery only

- Public channel: https://t.me/newssmartlab
- Collector: `python -m research_agent.fundamentals.smartlab_collector`
- Reads Telegram's public web preview at `https://t.me/s/newssmartlab`; no bot
  token, logged-in account, paid API, or Finam integration is needed.
- Keeps posts only when an explicit ticker tag/token matches one of the 44
  configured MOEX constituents. Short tickers require a hashtag or dollar
  prefix to avoid false matches.
- Stores post text, publication timestamp, post URL, ticker(s), and a simple
  reporting-related keyword flag. Every item is marked
  `unverified_news_lead`, not a verified issuer disclosure.
- The public preview exposes only a recent slice, not a complete archive.

### MOEX CCI report metadata — access may be restricted

- Calls MOEX CCI company-reference and corporate-report metadata endpoints.
- Stores source rows and a normalized report index; publication timestamp is
  kept separate from reporting-period end.
- Does not assume structured IFRS/RAS datasets are free. HTTP 401/403 and
  missing datasets are recorded as source limitations.
- Documentation: https://www.moex.com/a2836 and
  https://www.moex.com/tsentr-korporativnoj-informatsii

## Data integrity rules

- Smart-Lab is a news-discovery source, not a source of record.
- Before extracting figures, retrieve the issuer's original disclosure/report
  and retain its URL, publication time, period, accounting standard,
  consolidated/standalone scope, currency, units, and content hash.
- Never substitute reporting-period end for publication time.
- Fuzzy issuer/ticker matching is disabled. Missing values remain null.
- Restatements and historical versions must be preserved before point-in-time
  backtests are considered valid.
- Fundamental data is a slow-moving research context, not an H1 entry timer.

## Workflow and safety

The GitHub Actions workflow is manual-only until free-source access and
coverage are verified. It runs tests and stores research snapshots on
`research/price-forecast-24h-v1`. No scheduled polling is enabled.

No production signals, live orders, Telegram notification bot, secrets,
cron-job.org schedule, or Finam settings are changed by this module.
