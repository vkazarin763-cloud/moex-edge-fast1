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

## Liquidity and collection design

- The 44 symbols are a candidate pool only.
- Rank candidates using official MOEX ISS TQBR daily `VALUE`, not `close × volume`.
- The prospective collector requires at least 40 valid positive `VALUE` observations among the latest 60 completed D1 rows and selects the top 10 by mean turnover.
- Fetch H1 only for the selected top 10; retain D1 screening records for all candidates and persist the complete selection metadata in each snapshot.
- Securities without sufficient official `VALUE` history are excluded from eligibility and recorded by absence from the ranking; no proxy is imputed.
- The top-10 cohort is recomputed at each manual collector run. It is point-in-time per snapshot, not a fixed retrospective cohort.
- The fixed current 44-symbol candidate pool creates survivorship/universe-selection bias for historical evaluation.

## Limitations

The inspected artifact's validator confirms structural integrity only for that snapshot. It does not prove prospective collection quality, point-in-time universe correctness, or model validity. The existing H1 feed lookback is 30 calendar days. No model was trained, no signal generated, no workflow dispatched, and no production/trading configuration changed as part of this audit.
