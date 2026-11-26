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

## Data-access and licensing gate

The official MOEX ISS documentation states that unauthenticated market data is delayed (typically 15 minutes), historical data under `/iss/history` is subscriber-only except for indices, and ISS information is for familiarization only; use for profit-making or other non-familiarization purposes requires an agreement with MOEX. Therefore a free public ISS endpoint must not silently become the production data source for a profitable trading system.

Before replay, use one of these lawful/usable routes:
1. A data entitlement/provider agreement that explicitly permits algorithmic/research use of the required option market data; or
2. An existing connected provider feed whose terms permit this use and whose API exposes actual option-contract quotes/trades.

The existing Finam AI Screener connection is not the data source for this task. Separately, the official Finam Trade API documents a read-only options-chain endpoint (`GET /v1/assets/{underlying_symbol}/options`), latest quote endpoint (including option implied volatility and Greeks), order-book and latest-trades endpoints, plus historical bars. The documented history depth is H1 up to 30 days and D1 up to 365 days. This gives us a practical existing-provider route for a read-only contract discovery probe without adding a paid service or reconfiguring the Screener. It does **not** by itself prove that long historical bid/ask snapshots are available; the initial probe must verify actual contract coverage and quote freshness. Do not call any order endpoint.

Finam API references:
- REST API: https://api.finam.ru/docs/rest/ (OptionsChain, LastQuote, OrderBook, LatestTrades, Bars)
- gRPC/API reference: https://api.finam.ru/docs/grpc/ (OptionsChain request/response and option metadata)
- Finam quick start for latest quotes and historical bars: https://api.finam.ru/getting-started/bystryy-start/poluchit-kotirovku-i-istoriyu/

The exchange publishes a daily theoretical option price/volatility table (`/iss/history/engines/futures/markets/options/volat`), but theoretical prices are not executable bid/ask and cannot replace real quotes in the performance replay.

Official data references:
- MOEX ISS API overview and usage restrictions: https://www.moex.com/a2193
- MOEX ISS developer manual (historical access limitations): https://www.moex.com/files/4be999zbzp80bx2bgmwayrtyx0
- MOEX theoretical options price/volatility publication: https://fs.moex.com/f/21878/informacija-o-teoreticheskoy-cene-opcionov.pdf
- MOEX historical data service description: https://www.moex.com/a2863

## First live data-access probe — 2026-11-26

GitHub Actions run 45876826635 completed successfully. Authentication to Finam succeeded; all four options-chain requests returned successfully:

- GAZP@MISX: 108 contracts in returned chain
- SBER@MISX: 134
- ROSN@MISX: 112
- MOEX@MISX: 198
- Total: 552 option records returned; 48 sampled contract quote requests completed.
- **0/48 sampled contracts had a valid positive bid and ask at the same time.** Some responses had ask-only values; all sampled open-interest values were zero.
- The sampled contracts reported expiration_last_day 2030-12-18, which does not match the intended near-term 20–60 day selection and must be reconciled against the contract metadata / exact chain filters.
- Underlying spot quotes were returned for all four symbols.
- No account, order, cancel, or SL/TP endpoint was called.

Interpretation: the API route is reachable, but this probe does **not** yet establish executable option liquidity. Do not issue option signals or claim the strategy is ready. A follow-up read-only diagnostic now checks option asset metadata, order books, and latest trades for a small sample to identify why quotes are empty/one-sided and why the returned expiry date is unusual. If contract-level executable quotes remain unavailable, stop and mark the current Finam data route insufficient rather than inventing prices.

Artifact from the first probe: GitHub Actions artifact `moex-options-readonly-probe`, run 45876826635 (retained for 7 days).

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

- Research-only. Finam Trade API market-data GET endpoints may be used for a read-only probe; do not call account, broker, order, cancel, or SL/TP endpoints. No live mode or Telegram integration.
- Do not modify production repositories, existing live-execution workflows, scheduled workflows, frozen equities strategies, or the user's fundamentals branch.
- Do not create a new paid service or request new secrets.
- Keep this work separate from MOEX EDGE's frozen equities research and from the trend-forecast PR #191.
- The user should not be asked to perform manual audits or copy/paste technical data. Report only completed, independently verified work and clearly state blockers.
