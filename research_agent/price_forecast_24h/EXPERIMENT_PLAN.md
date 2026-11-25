# MOEX 24H Price Forecast — experiment plan

Status: PLAN ONLY. No model, signal, workflow, or production code has been implemented.

## Objective

For the most liquid shares in the existing 44-symbol MOEX research candidate pool, forecast both:

1. the direction of the price move (LONG / SHORT / FLAT);
2. the magnitude of the move as a percentage;
3. a prediction interval for the forward price.

This is a research forecast, not a trading recommendation or order instruction.

## Isolation and safety

- Dedicated branch: `research/price-forecast-24h-v1`, created from `main`.
- Keep all changes on this branch. Do not merge or open a PR unless explicitly requested.
- Do not modify `main`, production repository `moex-edge`, the separate options repository `moex-edge-fast`, the frozen D1 strategy cohort, existing scanner workflows, AI Trader state, Finam executor, broker/account/order integrations, Telegram, secrets, schedules, or live-mode settings.
- Read-only market data only. No account endpoints and no order endpoints.
- No real or virtual trades are required for this experiment.
- No automatic strategy promotion. A positive research result only earns a separate validation proposal.

## Forecast horizon and target

- Forecast origin: immediately after a fully completed H1 candle.
- Primary horizon: the next **24 completed H1 bars** (24 exchange-data trading hours; usually spread over roughly three MOEX sessions, not 24 wall-clock hours).
- Target return: `100 * (close[t+24] / close[t] - 1)`.
- Direction label: LONG for a positive move, SHORT for a negative move, FLAT inside a pre-registered neutral band.
- The neutral band must be fixed using training-only data and a documented cost/noise rule before evaluation. Do not choose it after looking at holdout results.
- If a symbol lacks 24 valid future H1 bars, the observation is excluded with a recorded reason. Never forward-fill, interpolate, or fabricate a target.
- Forecast price = current completed close multiplied by the predicted return. Prediction intervals must be estimated on training/validation data only and assessed for empirical coverage.

## Universe: most liquid shares

- Candidate pool: the repository's existing 44-symbol MOEX share universe.
- Rank securities at each forecast origin using trailing 60 completed MOEX trading sessions of daily RUB turnover (close × traded volume), calculated only from information available at that origin.
- Select the top 10 eligible securities at each origin; require at least 40 valid daily observations in the lookback. Freeze the selection for that origin before generating a forecast.
- Recompute the ranking on a documented schedule (initially once per trading week) using only then-available data.
- Record each date's selected symbols and turnover ranks in the dataset/report.
- Important limitation: the 44-symbol candidate pool is a fixed current universe. Unless point-in-time historical index membership is available, results must explicitly disclose survivorship/universe-selection bias and must not be described as a complete historical MOEX market test.
- Do not rank by future returns, model scores, or evaluation-period performance.

## Data audit — mandatory first gate

1. Inspect the existing audited MTF candle artifacts and their exact run IDs, timestamps, checksums, frame coverage, and retention.
2. Verify how much usable H1 history is actually available. The documented collector limit for intraday H1 is 30 calendar days; do not assume the short archive is sufficient for model training.
3. Verify timestamps, timezone, completed-bar status, session/weekend labels, duplicate timestamps, monotonicity, OHLC consistency, finite values, and volume validity.
4. Use daily turnover from a documented source with consistent currency/volume units. Confirm corporate-action/adjustment conventions before combining D1 and H1 data.
5. Do not mix providers or resample/fill one source with another unless a separate validation proves the transformation safe.
6. If the available clean H1 history is insufficient for a meaningful 24-bar target and chronological splits, stop the retrospective backtest. Propose a read-only prospective data collection plan instead; do not quietly extend the sample or invent data.

## Models to compare

Use a small, frozen model set; no broad hyperparameter search in the first pass.

1. **Zero-return baseline:** predicts no price change; benchmark for magnitude error.
2. **Historical-drift baseline:** predicts the training-only mean/median 24-bar return, with direction from its sign.
3. **Momentum/trend baseline:** fixed return, EMA-distance, and volatility features with parameters documented before evaluation.
4. **Regularized linear models:** Ridge regression for return magnitude and logistic regression for direction.
5. **One nonlinear challenger:** a small tree-based regressor/classifier only if the installed dependency and sample size justify it; otherwise omit it rather than adding heavyweight dependencies.

All models must use the same eligible observations and point-in-time universe. Fit scalers, feature selection, thresholds, and calibration only on the training portion.

## Feature policy

Candidate features known at the forecast origin:

- lagged H1 returns over fixed windows (1, 3, 6, 12, 24 bars);
- candle body/range and close location;
- volume and relative-volume changes;
- EMA distance/slope and RSI;
- rolling realized volatility and ATR-normalized movement;
- market-wide context computed only from the same point-in-time eligible data.

No future bars, centered windows, revised future constituents, or target-derived features. OHLCV volume is not order flow and must not be described as buyer/seller aggressor data.

## Validation design

- Use strictly chronological train / validation / final test blocks.
- Purge observations whose 24-bar target overlaps a later split; apply an embargo of at least 24 H1 bars at split boundaries.
- Keep all symbols from the same forecast timestamp in the same split.
- Tune and select models only on training/validation data. Open the final test exactly once after the method is frozen.
- Report performance by ticker, date, market regime, and forecast horizon; also report pooled results with uncertainty intervals.
- Do not reuse the earlier five-session H1 quick-rejection window as the sole evidence of success.
- Keep this experiment's split dates independent of the existing frozen D1 scanner cohort. Do not inspect or alter that cohort's prospective holdout.

## Required metrics

### Direction
- LONG / SHORT / FLAT counts and coverage;
- accuracy, balanced accuracy, per-class precision/recall and confusion matrix;
- Brier score / calibration for directional probabilities where available.

### Magnitude and price
- MAE and RMSE of the 24-bar percentage return;
- median absolute error;
- directional hit rate conditional on confidence;
- prediction-interval coverage and width;
- comparison with zero-return and historical-drift baselines.

### Economic sensitivity (diagnostic only)
- Show gross and net directional returns under explicitly stated per-symbol fee and slippage assumptions.
- Treat costs as assumptions until verified from actual instrument tariffs and realistic execution data.
- Include turnover and exposure frequency; do not calculate portfolio capital, position sizes, or allocations.
- A model is not considered useful merely because it has high raw accuracy; it must improve on baselines and retain value after plausible costs.

## Promotion gate

No deployment, Telegram notifications, workflow scheduling, or strategy change from this branch.

A model may be proposed for a separate prospective paper test only if:
- data quality and point-in-time universe selection pass;
- final chronological test beats the relevant baselines on both direction and magnitude;
- performance is not concentrated in one ticker or one short market regime;
- uncertainty is reported and results remain useful under plausible costs;
- prediction intervals are reasonably calibrated;
- all leakage and regression tests pass.

If the data gate fails or no model beats the baselines, record the negative result and stop rather than tuning endlessly.

## Deliverables

1. This pre-registration plan.
2. Data-availability and quality audit with exact provenance.
3. Deterministic dataset builder and leakage/target tests (only after the data gate passes).
4. Reproducible training/evaluation script with frozen model definitions.
5. Final report containing metrics, baselines, limitations, and a clear accept/reject decision.

## Immediate next action

Perform only a read-only audit of existing artifacts and source availability to determine whether a valid historical 24-H1-bar experiment is feasible. Do not implement models until that gate is passed.
