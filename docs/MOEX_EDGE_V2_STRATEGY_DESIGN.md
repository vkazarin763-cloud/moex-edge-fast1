# MOEX EDGE v2 — strategy research design

Status: proposal only. No strategy in this document is approved, profitable, or authorized for production use.

## 1. Version boundary

- Keep `v1-frozen-2026-11-19`, its five candidate definitions, holdout start, execution assumptions, results, registry, and signal ledger unchanged.
- Build v2 in a separate namespace and separate registry. Do not overwrite v1 artifacts or prospective observations.
- v2 starts as a new development experiment. Its own candidate definitions, data fingerprint, cutoff, and prospective holdout must be frozen before prospective observations are inspected.
- The scanner may expose v2 research candidates separately from any strategy that passes v2 validation. Research candidates are not trade recommendations or broker authorization.

## 2. Candidate strategies for v2

The candidates below are selected because they represent established empirical ideas, not because their profitability on MOEX is known. Parameters are proposed starting definitions and must be frozen before testing; they must not be optimized against the final holdout.

### V2-01 — Time-series momentum (12–1)

- At each monthly formation date, calculate the security's total price return from approximately 12 months ago to one month ago (skip the most recent month).
- LONG when the trailing 12–1 return is positive; SHORT when it is negative.
- Hold to the next monthly rebalance; evaluate alternative fixed holding windows only as separately registered hypotheses.
- Requires a consistent corporate-action price basis and a clearly defined monthly formation calendar.
- Literature basis: Moskowitz, Ooi & Pedersen (2012), *Time Series Momentum*, Journal of Financial Economics. Their evidence concerns diversified futures markets, so transfer to individual MOEX shares is an untested hypothesis.

### V2-02 — Cross-sectional momentum (12–1 ranking)

- At each monthly formation date, rank the eligible universe by 12–1 return.
- LONG the top quintile and SHORT the bottom quintile, with deterministic tie handling and a predeclared minimum-liquidity rule.
- Evaluate as a portfolio of contemporaneous ranks, not as 44 independent ticker strategies.
- Requires point-in-time universe membership, delisting/suspension handling, and survivorship-bias controls. The current fixed 44-share list must not be assumed to represent historical membership throughout the sample.
- Literature basis: Jegadeesh & Titman (1993), *Returns to Buying Winners and Selling Losers*, Journal of Finance. Their US-equity results motivate a test; they do not establish a MOEX edge.

### V2-03 — 52-week-high momentum

- Calculate each share's close divided by its rolling 252-trading-session high, using only information available at formation.
- Rank securities by proximity to the 52-week high; test a predeclared long selection rule and a separately labelled short-side hypothesis rather than assuming symmetry.
- Rebalance monthly; evaluate returns after realistic costs.
- Requires a consistent price basis and point-in-time universe.
- Literature basis: George & Hwang (2004), *The 52-Week High and Momentum Investing*, Journal of Finance. Evidence is not MOEX-specific.

### V2-04 — Relative strength versus IMOEX

- Estimate each share's rolling market beta using only trailing data available at formation.
- Calculate cumulative residual/abnormal return versus IMOEX over a fixed six-month lookback, with a one-month skip.
- LONG positive residual-strength candidates and SHORT negative residual-strength candidates, subject to a predeclared minimum data/liquidity gate.
- This is a benchmark-relative hypothesis, distinct from raw own-price momentum. Validate beta stability and index alignment.
- Requires synchronized, corporate-action-consistent share and IMOEX series.

### V2-05 — Pairs mean reversion (data-gated)

- Generate candidate pairs only from an ex-ante formation window; estimate hedge ratio and test spread stationarity using formation data only.
- Trade deviations of the frozen spread z-score from its formation mean; close at a predeclared reversion threshold or risk boundary.
- Re-estimate pairs only on scheduled formation dates. Never select pairs using the future trading window.
- Treat each pair as one joint trade with both legs, costs on both legs, borrow/short availability constraints, and a portfolio-level exposure ledger.
- This candidate is NOT ready for implementation until the project has a validated corporate-action-adjusted price basis, reliable liquidity/shortability inputs, and pair-level point-in-time data. Gate it as `DATA_NOT_READY`, not as a failed strategy.
- Literature basis: Gatev, Goetzmann & Rouwenhorst (2006), *Pairs Trading: Performance of a Relative-Value Arbitrage Rule*, Review of Financial Studies. Their historical result does not establish current MOEX pair profitability.

## 3. Deliberately excluded from the first v2 cohort

Short-term reversal is not included initially. Published evidence links short-horizon reversals to liquidity provision, trading frictions, and market microstructure; the current project data does not yet provide a robust historical bid-ask spread/market-impact series. A volume-only filter is not an adequate substitute. It can be reconsidered when suitable liquidity data is available.

## 4. Required architecture

The v2 engine must support two evaluation levels:

1. **Single-security time-series evaluator** for V2-01 and V2-03.
2. **Synchronized panel/portfolio evaluator** for V2-02, V2-04, and V2-05.

The panel evaluator must align all instruments and benchmark observations to common formation timestamps, use only information available at each timestamp, and model simultaneous entries/exits, both legs of pair trades, costs, missing data, and portfolio constraints. It must not route panel strategies through the v1 per-ticker `generate_signals()` / registry path.

Each candidate must produce explicit states:
- `PASS`: all pre-registered development gates satisfied;
- `REJECT`: adequate data but one or more pre-registered performance/robustness gates failed;
- `INSUFFICIENT_DATA`: required sample is not adequate;
- `DATA_NOT_READY`: required source/quality fields are unavailable.

Do not lower sample thresholds to force a PASS. Multiple-testing correction must cover the full pre-registered strategy/parameter/universe family, including panel-level hypotheses.

## 5. Data and bias gates before performance testing

- Reconcile raw D1 bars to official TQBR history and retain all discrepancy diagnostics.
- Establish a documented corporate-action-adjusted or same-share-basis series; do not silently splice split/consolidation price scales.
- Build a point-in-time eligible universe or explicitly limit conclusions to the present-day 44-name cohort and label survivorship bias.
- Add IMOEX data on matching dates and verify calendar alignment.
- Establish a point-in-time liquidity measure (preferably traded value and, where available, spread/market impact); share volume alone is insufficient.
- Preserve missing sessions, suspensions, listing dates, and zero-trade observations as distinct states.
- Freeze all signal, rebalance, exit, cost, and portfolio rules before examining the new prospective holdout.

## 6. Validation policy

- Keep development, validation, and prospective holdout chronologically separated.
- Use rolling/expanding walk-forward tests with no overlapping leakage between formation and test windows.
- Report both strategy-level and portfolio-level results; never present summed per-trade returns as portfolio return.
- Include realistic two-sided commissions, slippage, market impact where measurable, and short-sale constraints.
- Report trade count, turnover, exposure, drawdown, concentration, period/regime breakdown, and sensitivity to costs.
- Apply family-wise multiple-testing correction to the complete registered family.
- A historical screen is not proof of future profitability. Prospective observations must remain untouched.

## 7. Implementation order

1. Implement and test the v2 data contract and corporate-action/universe gates.
2. Implement V2-01 and V2-03 in the single-security evaluator.
3. Implement V2-02 and V2-04 in the synchronized panel evaluator.
4. Implement V2-05 only after its data-readiness gate is met.
5. Add a v2 registry and separate shadow-candidate output; leave v1 scanner and registry intact until v2 is independently validated.
6. Run safety tests and verify all required workflows on the exact PR head SHA before merge.

## 8. Research references

- Moskowitz, Ooi & Pedersen (2012), *Time Series Momentum*, Journal of Financial Economics, https://doi.org/10.1016/j.jfineco.2011.11.003
- Jegadeesh & Titman (1993), *Returns to Buying Winners and Selling Losers*, Journal of Finance, https://doi.org/10.1111/j.1540-6261.1993.tb04702.x
- George & Hwang (2004), *The 52-Week High and Momentum Investing*, Journal of Finance, https://doi.org/10.1111/j.1540-6261.2004.00695.x
- Gatev, Goetzmann & Rouwenhorst (2006), *Pairs Trading: Performance of a Relative-Value Arbitrage Rule*, Review of Financial Studies, https://doi.org/10.1093/rfs/hhj020
