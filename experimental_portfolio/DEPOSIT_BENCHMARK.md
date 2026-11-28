# RUB deposit hurdle — research policy

**Snapshot date:** 2026-11-27  
**Scope:** forward-looking research comparison only; no trading or allocation.

## Current reference

The Bank of Russia's 27 November 2026 monitoring reports a 13.33% headline average of maximum ruble deposit rates across ten major banks. Its term-specific indicative rates are:

| Deposit term | Annual rate |
|---|---:|
| Up to 90 days | 12.60% |
| 91–180 days | 13.18% |
| 181 days–1 year | 12.85% |
| Over 1 year | 11.96% |

Primary source: [Bank of Russia, 27 November 2026](https://www.cbr.ru/press/pr?file=639313833655037811BANK_SECTOR.htm).

These are indicative maximum average rates, not guaranteed offers to this account holder. Actual offers depend on bank, amount, new-money/client conditions, capitalization, early withdrawal and other terms. Rates above are gross before personal tax.

## How the research gate works

The benchmark module exposes a term-specific annualized hurdle and compares strategy CAGR against it. The default comparison requires the strategy to exceed the current deposit rate; an additional annual risk premium can be passed explicitly as required_excess_rate.

- Default one-year-ish weekly-research comparison: 12.85% (181 days–1 year).
- A strategy below the hurdle is marked BELOW_HURDLE.
- A strategy above the hurdle is marked ABOVE_HURDLE_NOT_APPROVED, never approved for live trading.
- Missing CAGR is NOT_COMPARABLE.
- Maximum drawdown is reported alongside return.
- The current snapshot is not retroactively applied as a historical deposit return.

## Limitations and next requirements

This is a current hurdle snapshot, not a historical deposit-rate time series. A fair historical comparison requires archived term-specific rates over the same dates and a matched deposit rollover/reinvestment assumption. Taxes must be calculated from actual tax circumstances before a net comparison; strategies also need realistic commissions, bid-ask spread, slippage, dividends/distributions and instrument fees.

Beating a deposit is only a candidate for further validation. It must still pass rolling walk-forward tests, regime splits, stability checks, liquidity/cost stress and instrument-specific risk controls. Bonds, futures and options require dedicated cash-flow, expiry, margin and payoff models; they must not be scored by this simple equity/fund CAGR comparator.

**Safety:** research and paper analysis only. No broker order endpoints, no live execution, no portfolio sizing.
