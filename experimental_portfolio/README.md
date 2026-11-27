# Autonomous Experimental Portfolio (Paper Only)

Isolated research portfolio. It does not import Finam executors, call broker APIs, or submit, amend, or cancel orders.

## First release
- Broad-market US-listed ETF proxies for US, developed ex-US, emerging, Europe, Japan and India equities; US Treasury bonds; gold; commodities; listed real estate; and a short-Treasury cash proxy.
- Public Yahoo Finance daily chart data, with Stooq CSV as a secondary fallback. OHLC rows are validated; Yahoo adjusted closes are used for total-return price history when present.
- Deterministic monthly strategy: select up to four assets with positive 63-session momentum and close above the 200-session SMA; equal-weight selected assets; otherwise remain in cash.
- Backtest starts with normalized NAV index 100. This is not a currency or the user's capital.
- Provisional 10-basis-point one-way turnover cost is disclosed in each report and is not represented as a broker-confirmed fee.
- Three independent reviewer roles (market context, strategy research, risk audit). They use OpenRouter first and Groq fallback when available. If providers reject requests or no key exists, transparent local deterministic reviewers still run; the report distinguishes LLM from local reviews. No reviewer can change weights or create trades.
- Daily workflow saves a dated JSON report, latest report and current paper-state snapshot to the repository.

## Deliberate limits
- This is a historical ETF-proxy experiment, not a live trading system or personalized allocation.
- Options and futures are not included in portfolio NAV yet. Options require trustworthy historical executable bid/ask, contract, expiry and liquidity data. Futures require expiry/roll, multiplier, margin and financing modeling. Existing MOEX option/futures scanners remain untouched.
- Daily closes are not live quotes or executable bid/ask. Dividend adjustments are used only where the provider supplies them. US-listed ETF proxies are not direct ownership of each foreign market and introduce currency and tracking risk.
- No capital amount, currency allocation or personal risk budget is assumed. NAV is normalized index units.
- Historical performance does not establish future profitability. Any real-money promotion requires separate evidence review and explicit user approval.
