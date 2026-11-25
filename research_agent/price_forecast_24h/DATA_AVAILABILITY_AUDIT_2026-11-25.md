# 24H Price Forecast — data availability audit (2026-11-25)

Status: **historical H1 sample insufficient for a credible model test.** No training, tuning, or predictive-skill claim is justified from the inspected archive.

## Inspected archive

- Repository: `vkazarin763-cloud/moex-edge-fast1`, branch `research/price-forecast-24h-v1`.
- Artifact: `moex-edge-multi-timeframe-candles`; workflow run `44889538524`; artifact ID `14701243872`.
- Artifact created 2026-11-21; 44 symbols; validation reported PASS and zero structural issues.
- H1: 44 symbols, 421–424 bars each, 2026-10-22 through 2026-11-21 (about 29 calendar dates).
- D1: 44 symbols, 249–253 bars each, approximately one year.

## Decision

The 24-H1-bar target and chronological splits with purge/embargo leave too little independent time coverage for a credible multi-regime test. Thousands of ticker-hour rows are not thousands of independent market observations. Accumulate at least 6 months of clean H1 history, preferably 12 months, before model evaluation.

## Updated collection universe decision (2026-11-25)

- User selected the complete 44-symbol universe instead of the proposed top-10 liquidity cohort.
- Collect H1 and D1 for all 44 symbols; do not filter out symbols based on official `VALUE`, liquidity rank, or missing turnover.
- Missing `VALUE` remains explicitly missing. Never estimate it from `close × volume`.
- A failure for one symbol or timeframe must be visible in that symbol's status and must not silently remove other symbols.
- The earlier top-10 selection design is superseded and must not be used by the active collector.
- The fixed current 44-symbol pool creates survivorship/universe-selection bias for historical evaluation.

## Limitations

The inspected artifact's validator confirms structural integrity only for that snapshot. It does not prove prospective collection quality, point-in-time universe correctness, or model validity. The existing H1 feed lookback is 30 calendar days. No model was trained, no signal generated, and no production/trading configuration changed as part of this audit.
