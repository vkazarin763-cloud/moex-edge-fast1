# Autonomous Experimental Portfolio (Paper Only)

Isolated research portfolio. It does not import Finam executors, call broker APIs, or submit, amend, or cancel orders.

## First release
- Broad-market US-listed ETF proxies for US, developed ex-US, emerging, Europe, Japan and India equities; US Treasury bonds; gold; commodities; listed real estate; and a short-Treasury cash proxy.
- Public Stooq daily OHLCV CSV data, strict row validation and explicit provider failures.
- Deterministic monthly strategy: select up to four assets with positive 63-session momentum and close above the 200-session SMA; equal-weight selected assets; otherwise remain in cash.
- Backtest starts with normalized NAV index 100. This is not a currency or the user's capital.
- Provisional 10-basis-point one-way transaction-cost assumption is disclosed in each report and is not represented as a broker-confirmed fee.
- Three independent AI reviewers (market context, strategy research, risk audit) use OpenRouter first and Groq as fallback. They cannot change weights or create trades. If no provider key is configured, deterministic reporting still runs and AI unavailability is recorded.
- Daily workflow saves a dated JSON report, latest report and current paper-state snapshot to the repository.

## Deliberate limits
- This is a historical ETF-proxy experiment, not a live trading system or personalized allocation.
- Options and futures are not included in portfolio NAV yet. Options require trustworthy historical executable bid/ask, contract, expiry and liquidity data. Futures require expiry/roll, multiplier, margin and financing modeling. Existing MOEX option/futures scanners remain untouched.
- Stooq data is end-of-day, not live or executable. US-listed ETF proxies are not direct ownership of each foreign market.
- No capital amount, currency allocation or personal risk budget is assumed. NAV is normalized index units.
- Historical performance does not establish future profitability. Any real-money promotion requires separate evidence review and explicit user approval.
