# H1 Direction Forecast — isolated research pilot

## Goal

Test whether the next completed H1 candle close is more likely to be above or below the current completed H1 close. Output is a research classification only: LONG / SHORT / NO SIGNAL. This is not an options strategy and does not place orders.

## Repository and safety boundary

- This work lives on `research/h1-direction-forecast-v1`, branched from `main`.
- Do not modify the frozen D1 strategy cohort, its prospective holdout, the existing MTF scanner, AI Trader state, scheduled workflows, Telegram, Finam executor, broker integrations, or production files.
- Read-only data only. No account endpoints, order endpoints, or secrets.
- Existing D1/H1 scanner predicts from D1 and uses H1 as confirmation; this pilot is a different task: H1-to-next-H1 direction.

## Data already available

The repository's audited 2026-11-21 multi-timeframe artifact contains Finam H1 bars for 44/44 symbols (18,781 completed H1 bars in total). Its independent structural audit reported no duplicate timestamps, invalid OHLCV, unsorted series, or incomplete bars at the snapshot boundary. The artifact is time-limited and must be checked for availability before use.

The collector documents a 30-calendar-day H1 history limit. Do not assume H1 history is available beyond that limit or treat technical weekend bars as regular MOEX-session bars without explicit labeling.

## Initial quick experiment

Use one frozen snapshot and the same eligible observations for every method.

- Development/training window: earlier bars in the available pre-holdout sample.
- Quick evaluation window: the final five completed MOEX trading sessions strictly before 2026-11-20 (the existing frozen D1 prospective holdout boundary).
- Exclude bars on/after 2026-11-20 from this initial pilot. Do not inspect or tune against the frozen prospective holdout.
- If the artifact does not contain enough clean pre-boundary H1 data, report insufficient data; do not silently extend into the sealed period.
- Target: direction of the next completed H1 close relative to the current completed H1 close. Near-zero moves are NO SIGNAL under a pre-registered noise threshold.
- Features may use only information available at the prediction candle close. Labels use exactly the next completed H1 bar. No overlapping future data, centered windows, or look-ahead.
- Keep chronological splits; all symbols sharing a timestamp stay on the same side of a split.

## Methods to compare

1. Naive baseline: previous H1 candle direction / majority direction, with no fitted parameters.
2. Technical baseline: EMA trend + short-term momentum, fixed before evaluation.
3. Simple ML baseline: regularized logistic regression with a small, fixed feature set (returns, candle body/range, volume change, EMA distance, RSI). Fit only on the development window.

Do not run a large parameter search or add indicators after seeing the five-day results.

## Required report

For each method and overall:
- eligible predictions, LONG / SHORT / NO SIGNAL counts;
- accuracy and balanced accuracy, plus precision/recall for each direction;
- directional return after an explicitly stated fee/slippage assumption;
- coverage and performance by ticker and session;
- comparison against the naive baseline;
- data provenance, last candle timestamp, excluded rows, weekend/session labeling, duplicate/invalid OHLCV counts;
- confidence intervals or a clear warning when the sample is too small.

A method is only a candidate for longer validation if it beats the naive baseline on the same observations, has both directions represented, and remains positive after costs. Five sessions are a fast rejection screen, not proof of durable profitability.

## Next steps

1. Verify and download the exact existing artifact; record its artifact ID, run ID, checksum, and snapshot time.
2. Implement the deterministic target/feature builder and leakage tests.
3. Implement the three fixed methods and chronological evaluation.
4. Run the pilot, publish a compact JSON/Markdown report, and leave all production paths untouched.
5. If promising, validate on a genuinely separate, longer period before any prospective/paper-monitoring phase.
