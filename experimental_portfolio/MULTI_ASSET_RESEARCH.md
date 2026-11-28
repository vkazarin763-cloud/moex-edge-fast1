# Universal Multi-Asset Research — isolated, paper-only

This programme is separate from the existing weekly MOEX fund portfolio and from all
legacy MOEX EDGE signal/live-execution paths.

## Scope and rollout

| Asset class | Discovery / research status | Gate before comparison |
|---|---|---|
| MOEX shares | Candidate registry included (44 index constituents) | Account-specific BUY permission + at least 200 validated weekly bars |
| MOEX exchange-traded funds | Candidate registry included (19 funds) | Account-specific BUY permission + at least 200 validated weekly bars |
| Bonds | Capability registered, not yet enabled | Coupon schedule, maturity, nominal, accrued interest, duration and cash-flow model |
| Futures | Capability registered, not yet enabled | Expiry, multiplier, margin, financing, roll method and continuous-contract validation |
| Options | Capability registered, not yet enabled | Contract specifications, historical executable bid/ask, expiry and payoff/risk model |

The registry is discovery metadata only. Candidate membership is **not** proof that an
instrument is listed, available to this Finam account, liquid, or suitable. Every
instrument must pass an account-scoped, read-only permission check and data validation.
Unknown or incomplete evidence fails closed.

## Research design

1. Preserve the current MOEX fund weekly strategy and its forward paper ledger as a
   separate control series.
2. Build independent weekly backtests for equities and funds; compare each strategy
   against a suitable benchmark and against cash, using identical observation dates.
3. Include transaction-cost and liquidity stress tests; report drawdown, volatility,
   turnover, data coverage and performance after costs.
4. Only compare asset classes after instrument-specific costs and risk models are
   implemented. Raw returns across unlevered securities and margined derivatives are
   not directly comparable.
5. Futures/options stay excluded from NAV until their contract-level models pass tests.

## Safety boundary

- Research and paper simulation only. No broker order endpoints, no live trading, and
  no changes to MOEX EDGE live/legacy executors or Telegram signals.
- No capital amount or personal allocation is assumed.
- No paid data or AI provider is introduced.
- AI reviewers may critique evidence but cannot approve assets, alter weights, or
  authorize orders.
