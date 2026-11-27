# Autonomous Experimental Portfolio (Paper Only — Finam account eligibility required)

Isolated research portfolio. It does not import Finam executors, call broker APIs, or submit, amend, or cancel orders.

## First release
- Broad-market US-listed ETF proxies are research candidates only. Portfolio positions are filtered by `finam_allowlist.json`; the allowlist is initialized empty and fails closed, so the portfolio stays 100% cash until account-specific Finam BUY permissions are verified.
- Public Yahoo Finance daily chart data, with Stooq CSV as a secondary fallback. OHLC rows are validated; Yahoo adjusted closes are used for total-return price history when present.
- Deterministic monthly strategy: select up to four assets with positive 63-session momentum and close above the 200-session SMA; equal-weight selected assets; otherwise remain in cash.
- Historical backtest is reported separately from the forward paper ledger. The forward ledger starts with normalized NAV 100 and no positions, then records only sessions observed after initialization. It uses prior-close signals and next-session open entries; missed dates are replayed in order.
- Provisional 10-basis-point one-way turnover cost is disclosed in each report and is not represented as a broker-confirmed fee.
- Three independent reviewer roles (market context, strategy research, risk audit). They use OpenRouter first and Groq fallback when available. If providers reject requests or no key exists, transparent local deterministic reviewers still run; the report distinguishes LLM from local reviews. No reviewer can change weights or create trades.
- Daily workflow saves a dated JSON report, latest report, current paper state and forward ledger to the repository.
- Account eligibility is a hard gate: only entries with `account_buy_permission=BUY_ALLOWED`, `verified_account_access=true`, and `verified_at` may be held. Do not manually whitelist based on exchange listing or general Finam availability. The account identifier is never committed.

## Finam eligibility gate

The initial `finam_allowlist.json` is intentionally empty. Account-specific verification must be completed through Finam's read-only instrument/account permission endpoints, with the result sanitized (no account ID, token, or credentials) and reviewed before adding approved symbols. Until then, historical analysis does not report performance for the unverified candidate universe and the forward paper portfolio remains in cash. If permissions are revoked, previously held virtual positions are excluded from the eligible set on the next run.

## Deliberate limits
- This is an ETF-proxy experiment, not a live trading system or personalized allocation.
- Options and futures are not included in portfolio NAV yet. Options require trustworthy historical executable bid/ask, contract, expiry and liquidity data. Futures require expiry/roll, multiplier, margin and financing modeling. Existing MOEX option/futures scanners remain untouched.
- Daily closes are not live quotes or executable bid/ask. Dividend adjustments are used only where the provider supplies them. US-listed ETF proxies are not direct ownership of each foreign market and introduce currency and tracking risk.
- No capital amount, currency allocation or personal risk budget is assumed. NAV is normalized index units.
- Historical results do not establish future profitability. Any real-money promotion requires separate evidence review and explicit user approval.
