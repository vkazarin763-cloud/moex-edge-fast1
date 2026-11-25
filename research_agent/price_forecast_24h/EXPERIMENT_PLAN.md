# MOEX 24H Price Forecast — experiment plan

Status: prospective read-only data collection and research plan. No forecasting model has been trained and no signal or trading integration is enabled.

## Objective

For the most liquid shares selected from the existing 44-symbol MOEX candidate pool, forecast:
1. Direction (LONG / SHORT / FLAT).
2. Magnitude of the next 24 completed H1 bars' price change, in percent.
3. A prediction interval for the forward price.

This is research, not a trading recommendation or order instruction.

## Universe and liquidity selection

- The 44 existing MOEX symbols are **only a candidate pool**, not the forecast universe.
- For each collection run, fetch completed D1 records for all 44 candidates from MOEX ISS TQBR history.
- Rank eligible candidates by mean official MOEX ISS `VALUE` (RUB traded value) over their latest 60 completed D1 sessions.
- Require at least 40 valid, positive, finite `VALUE` observations among those latest 60 rows. Exclude a security if its D1 source is not official MOEX ISS TQBR history or if it lacks sufficient valid `VALUE`. Never substitute `close × volume`.
- Select the top 10 eligible securities. Fetch H1 history **only for these 10**. D1 liquidity-screening data for all candidates is retained.
- Store the ranking, lookback count, valid-observation count, average turnover, last included session, and selected H1 cohort in every snapshot. Selection is point-in-time: the current run's cohort is frozen in its snapshot.
- The collector is manually dispatched; each run recalculates the cohort from data available at that run. Do not describe this as a fixed historical top-10 cohort.
- The 44-symbol pool is a fixed current candidate list. Without point-in-time historical constituents, results have survivorship/universe-selection bias and are not a complete historical MOEX market test.

## Forecast target

- Forecast origin: immediately after a fully completed H1 candle.
- Horizon: next **24 completed H1 bars** (24 exchange-data trading hours, generally spread over roughly three MOEX sessions).
- Return: `100 * (close[t+24] / close[t] - 1)`.
- Direction: LONG for positive move, SHORT for negative move, FLAT inside a neutral band fixed from training-only data before final evaluation.
- Exclude missing/invalid future bars; never forward-fill or fabricate targets.
- Convert predicted return to price using the latest completed close. Calibrate prediction intervals only on training/validation data.

## Data quality and collection

- H1 source: Finam completed bars; D1 turnover source: official MOEX ISS TQBR history. Do not merge providers or resample.
- H1 lookback from Finam is currently limited to 30 calendar days. Accumulate prospective immutable snapshots for at least 6 months, preferably 12 months, before meaningful model evaluation.
- Validate timestamps, completed-bar status, duplicates, monotonicity, OHLC consistency, finite values, volume, missing `VALUE`, and provider provenance.
- Historical H1 archive inspected on 2026-11-25 is too short for credible 24-bar model evaluation. Do not train or claim skill on it.
- Collection is read-only. No account, order, position, or execution endpoints.

## Models and validation

Compare zero-return and historical-drift baselines, fixed momentum/trend features, regularized linear regression/classification, and at most one small nonlinear challenger if sample size/dependencies justify it.
Use lagged H1 returns, candle geometry, volume/relative volume, EMA/RSI, realized volatility, and point-in-time market context only. OHLCV is not aggressor-side order flow.
Use chronological train/validation/test blocks, keep all symbols from one forecast timestamp in one split, purge overlapping 24-bar targets and embargo at least 24 H1 bars. Fit all transforms and thresholds on training only. Open final test once after freezing methodology.

## Metrics and promotion gate

Report direction coverage and per-class metrics, return MAE/RMSE, median absolute error, prediction interval coverage/width, per-symbol and per-regime breakdowns, uncertainty, and comparisons with baselines. Costs are diagnostic assumptions only until verified.
No deployment, Telegram, scheduling, or strategy changes from this branch. A separate paper-test proposal requires clean data, out-of-sample improvement over baselines, stability across symbols/regimes, calibrated intervals, plausible post-cost value, and passing leakage tests. Otherwise record the negative result and stop.

## Safety and isolation

All changes remain on `research/price-forecast-24h-v1`. Do not merge or open a PR unless explicitly requested. Do not touch production repo `moex-edge`, separate options repo `moex-edge-fast`, frozen D1 cohort, scanner workflows, AI Trader, Finam execution, broker/account/order integrations, Telegram, secrets, schedules, or live-mode settings.
