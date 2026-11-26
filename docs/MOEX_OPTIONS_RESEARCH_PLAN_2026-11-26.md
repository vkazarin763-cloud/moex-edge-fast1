# MOEX Options — Long Premium Research Plan v1

Date: 2026-11-26
Repository: `vkazarin763-cloud/moex-edge-fast1`
Branch: `research/moex-options-long-premium-v1`
Status: research specification only; no signals, no live trading, no broker/order integration.

## Objective

Find a simple, fully rule-based MOEX options strategy with convex upside and strictly limited premium risk. Evaluate both long calls and long puts across short, medium, and longer holding periods. The goal is not to guarantee uncapped profit: only long calls have theoretically unlimited upside; long puts are capped by the underlying falling to zero. A buyer can lose 100% of the premium.

## Important finding: the existing options backtest is not valid evidence

The current `options_backtest.py` must not be used to select or approve a strategy. Source review found material modeling problems:

- It requests futures candles for hard-coded futures symbols, not historical option-contract quotes/trades.
- It assumes a fixed 30% volatility and 15% rate for every underlying and date.
- It prices options with Black–Scholes instead of observed option bid/ask or transaction prices.
- It does not model actual contract multipliers, lot sizes, strike grids, exercise/settlement details, bid-ask spread, option liquidity, commissions, or slippage.
- The reported PnL mixes option-value units with underlying-price units and the linear comparison is not a valid return calculation.
- Its expiry handling uses the first bar after expiry and can label exits incorrectly.
- The strategy uses future candles from the signal timestamp without a rigorously defined next-bar execution and contract selection process.

Therefore any output from this script is synthetic and must not be described as a historical options backtest or profitability evidence. Keep it isolated; do not use its results.

## Exchange facts and initial liquidity shortlist

The MOEX derivatives statistics page recently displayed the following share-option underlying activity (daily snapshot shown on the page; the page's Russian table was dated 2026-11-23 16:25):

- GAZP: 727,131 contracts / 887 trades / 35,255,072 open interest
- SBER: 111,026 / 331 / 7,099,196
- ROSN: 26,501 / 114 / 7,481,196
- VKCO: 17,327 / 101 / 117,076
- MOEX: 10,426 / 42 / 2,147,384
- ALRS: 7,001 / 24 / 28,910,002

These are underlying-level option-market aggregates, not proof that any particular strike/expiry is liquid. The first contract-level screening shortlist is GAZP, SBER, ROSN and MOEX. Include another underlying only if its individual option contracts pass quote-quality filters.

Official references:
- MOEX derivatives market statistics: https://www.moex.com/ru/derivatives/maininfo.aspx
- MOEX contract search: https://www.moex.com/en/derivatives/contracts.aspx
- MOEX explanation of options: https://www.moex.com/msn/en-what-are-options
- MOEX stock-options FAQ (European, cash-settled; exercise only at expiry): https://www.moex.com/a8167

## Candidate strategy to evaluate first

**Trend-confirmed long premium breakout** (one ruleset, no parameter mining):

1. Underlying signal uses only fully closed H1 bars.
2. CALL candidate: close above the prior 20 completed H1-bar high and EMA20 > EMA50.
3. PUT candidate: close below the prior 20 completed H1-bar low and EMA20 < EMA50.
4. Entry occurs no earlier than the next executable option quote after the underlying signal. Never assume a fill at the underlying close.
5. Select an actual listed contract with 20–60 calendar days to expiry, strike nearest the underlying forward/spot reference (ATM first; one adjacent strike may be compared only as a predeclared sensitivity).
6. Require valid, timestamped bid and ask, positive bid, ask >= bid, and contract-level liquidity. Reject crossed/stale quotes and contracts with spread > 10% of mid or insufficient displayed depth/turnover. These are initial conservative filters, to be frozen before replay.
7. Buy at ask; mark/exit at bid. Include exchange/broker commissions and any applicable fees. No mid-price fills.
8. Exit on the earliest of: opposite underlying breakout on a completed H1 bar; 50% premium loss; 100% premium gain; or a predeclared time exit before expiry (e.g. 5 trading days remaining). Compare these fixed exits with hold-to-expiry only as a separate benchmark.
9. Maximum loss is the paid premium plus fees. Do not average down, sell uncovered options, or pyramid.
10. If no qualifying contract/quote exists, output NO TRADE. No forced signals.

This is a candidate hypothesis, not a proven profitable strategy. The 50%/100% exits and 20–60 day expiry band are fixed starting rules, not optimized parameters.

## Required data before any backtest claim

For every candidate signal, preserve:
- Underlying H1 candles and source timestamps.
- Exact option security/contract identifier, call/put, strike, expiry, contract multiplier and settlement style.
- Historical option bid, ask, trade price/volume and open interest at the decision and exit times, where available.
- Quote timestamp/age and market session.
- Fees, lot size, tick size, and realistic fill assumptions.

If historical quote depth or executable bid/ask is unavailable, the result must be labelled a limited trade-price replay or untestable, never a full executable backtest.

## Evaluation — one short, bounded pass

- Use the four-symbol shortlist first; do not expand the universe automatically.
- Use real contract data only. No fixed-volatility Black–Scholes values as substitutes for observed prices.
- Separate development and chronological holdout periods; no tuning on holdout.
- Report number of eligible contracts, rejected quotes and reasons, completed trades, net PnL per premium paid, win rate, profit factor, max drawdown, expectancy, and benchmark comparison.
- Stress costs and slippage; buy at ask and sell at bid is the baseline.
- Require enough trades and more than one market regime. If data quality or sample size is inadequate, stop and report INCONCLUSIVE.
- Compare CALL and PUT separately and report holding horizons separately.
- A strategy is not promoted based on win rate alone; require positive net expectancy and robustness to cost stress.

## Operational boundaries

- Research-only. No Finam account, broker, order endpoint, live mode, or Telegram integration.
- Do not modify production repositories, existing live-execution workflows, scheduled workflows, frozen equities strategies, or the user's fundamentals branch.
- Do not create a new paid service or request new secrets.
- Keep this work separate from MOEX EDGE's frozen equities research and from the trend-forecast PR #191.
- The user should not be asked to perform manual audits or copy/paste technical data. Report only completed, independently verified work and clearly state blockers.
