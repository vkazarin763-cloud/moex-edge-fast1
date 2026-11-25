# MOEX 24H Price Forecast — experiment plan

Status: prospective read-only data collection and research plan. No forecasting model has been trained and no signal or trading integration is enabled.

## Objective

For **all 44 shares in the current MOEX candidate universe**, forecast:
1. Direction (LONG / SHORT / FLAT).
2. Magnitude of the next 24 completed H1 bars' price change, in percent.
3. A prediction interval for the forward price.

This is research, not a trading recommendation or order instruction.

## Universe

- The forecast and collection universe is the complete fixed list of 44 symbols in `research_agent.multi_timeframe.DEFAULT_TICKERS`.
- Collect H1 Finam and D1 MOEX ISS TQBR history for every symbol on each run.
- **No liquidity-based inclusion or exclusion.** Liquidity may be measured and reported descriptively, but must not determine which symbols are collected or forecast.
- Preserve each symbol's source, status, row counts, last timestamp, and data-quality issues. A symbol with missing H1 or D1 data remains in the report with an explicit status; do not silently drop it.
- Never replace official MOEX ISS `VALUE` with `close × volume`. Missing `VALUE` is recorded as missing and does not prevent collecting price bars.
- The fixed current 44-symbol pool may create survivorship/universe-selection bias for historical evaluation. This limitation must be stated.

## Forecast target

- Forecast origin: immediately after a fully completed H1 candle.
- Horizon: next **24 completed H1 bars** (24 exchange-data trading hours, generally spread over roughly three MOEX sessions).
- Return: `100 * (close[t+24] / close[t] - 1)`.
- Direction: LONG for positive move, SHORT for negative move, FLAT inside a neutral band fixed from training-only data before final evaluation.
- Exclude missing/invalid future bars; never forward-fill or fabricate targets.
- Convert predicted return to price using the latest completed close. Calibrate prediction intervals only on training/validation data.

## Data quality and collection

- H1 source: Finam completed bars; D1 source: official MOEX ISS TQBR history, with any Finam fallback explicitly labeled. Do not merge providers or resample.
- Initial H1 history was backfilled once for 180 calendar days. The canonical `data/H1_HISTORY.json.gz` archive is seeded from that backfill and incrementally extended with only newly completed bars on each weekday collection. The Finam request remains a rolling <=30-calendar-day window; the full history is not downloaded again. Daily deltas remain immutable audit snapshots.
- Validate timestamps, completed-bar status, duplicates, monotonicity, OHLC consistency, finite values, volume, missing `VALUE`, and provider provenance.
- Report per-symbol H1/D1 status, bars received, last available date, missing fields, and errors. One symbol's data failure must not stop collection of the other symbols.
- Historical H1 archive initially backfilled on 2026-11-25 contains about six months of technical Finam bars. Treat first walk-forward results as exploratory; extend the same cumulative archive daily and rerun validation as history grows.
- Collection is read-only. No account, order, position, or execution endpoints.

## Models and validation

Compare zero-return and historical-drift baselines, fixed momentum/trend features, regularized linear regression/classification, and at most one small nonlinear challenger if sample size/dependencies justify it.
Use lagged H1 returns, candle geometry, volume/relative volume, EMA/RSI, realized volatility, and point-in-time market context only. OHLCV is not aggressor-side order flow.
Use chronological train/validation/test blocks, keep all symbols from one forecast timestamp in one split, purge overlapping 24-bar targets and embargo at least 24 H1 bars. Fit all transforms and thresholds on training only. Open final test once after freezing methodology.

## Metrics and promotion gate

Report direction coverage and per-class metrics, return MAE/RMSE, median absolute error, prediction interval coverage/width, per-symbol and per-regime breakdowns, uncertainty, and comparisons with baselines. Costs are diagnostic assumptions only until verified.
No deployment, Telegram, or strategy changes from this branch. The only schedule permitted here is the weekday read-only market-data collector that appends to the cumulative research archive. A separate paper-test proposal requires clean data, out-of-sample improvement over baselines, stability across symbols/regimes, calibrated intervals, plausible post-cost value, and passing leakage tests. Otherwise record the negative result and stop.

## Safety and isolation

All changes remain on `research/price-forecast-24h-v1`. Do not merge or open a PR unless explicitly requested. Do not touch production repo `moex-edge`, separate options repo `moex-edge-fast`, frozen D1 cohort, scanner workflows, AI Trader, Finam execution, broker/account/order integrations, Telegram, secrets, schedules, or live-mode settings.
