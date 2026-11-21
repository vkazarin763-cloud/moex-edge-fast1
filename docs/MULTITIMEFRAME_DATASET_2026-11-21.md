# MOEX EDGE — multi-timeframe dataset audit (2026-11-21)

## Provenance
- Repository: https://github.com/vkazarin763-cloud/moex-edge-fast1
- Workflow run: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/44861047844
- Run ID: 44861047844; result: SUCCESS; job: collect.
- Commit: a65eeaf3800be1b56deaaa36258a5369fce33cf2 (PR #71 merged).
- Artifact: moex-edge-multi-timeframe-candles; artifact ID: 14690518588; retention: 30 days.
- ZIP SHA-256: `6a9ee767f37bec1f9fa9d40d0868ccc8f36b2271dd5ef4a1715f83e4a51af137`.
- Snapshot as-of: 2026-11-21T03:25:33.304483+00:00 (Europe/Moscow 06:25:33).
- Files: `moex_edge_multi_timeframe_candles.json`, `moex_edge_multi_timeframe_validation.json`.

## Summary
- Universe: 44 frozen symbols; every symbol has data in all 13 frames.
- Total bars: 787,929.
- Validator: PASS; issue_count=0.
- Independent recheck: 0 duplicate timestamps; 0 non-monotonic sequences; 0 invalid/non-finite OHLCV; 0 OHLC consistency violations; 0 negative volume; 0 Finam snapshot=true bars; 0 bars whose calculated native interval end exceeds as-of.

## Exact frame totals

| Provider | Frame | Symbols with data | Completed bars |
|---|---:|---:|---:|
| Finam | M1 | 44/44 | 247,364 |
| Finam | M5 | 44/44 | 218,870 |
| Finam | M15 | 44/44 | 74,160 |
| Finam | M30 | 44/44 | 37,256 |
| Finam | H1 | 44/44 | 18,781 |
| Finam | H2 | 44/44 | 10,114 |
| Finam | H4 | 44/44 | 5,500 |
| Finam | H8 | 44/44 | 3,344 |
| MOEX ISS | M10 | 44/44 | 110,962 |
| MOEX ISS | W1 | 44/44 | 10,088 |
| MOEX ISS | MN | 44/44 | 2,322 |
| MOEX ISS | QR | 44/44 | 750 |
| MOEX ISS TQBR history | D1 | 44/44 | 48,418 |
| **Total** | | | **787,929** |

## Exclusions and data policy
- Finam intraday: snapshot=true excluded = 0; incomplete bars excluded = 0; unknown snapshot flags retained = 0.
- MOEX ISS M10 incomplete bars excluded = 0.
- MOEX ISS W1 incomplete bars excluded = 44; MN = 44; QR = 44.
- Native D1 TQBR history: zero-trade rows excluded = 826; incomplete/invalid rows excluded = 0.
- Finam timestamps are timezone-aware UTC. Naive MOEX ISS timestamps are interpreted as Europe/Moscow.
- Native interval completion is required before bars enter the as-of snapshot.
- D1 uses official per-security TQBR history with positive NUMTRADES and complete valid OHLCV. It is not derived from intraday data.
- No resampling, filling, interpolation, merging of Finam and MOEX feeds, or strategy decisions were performed by the collector.

## Interpretation / limitations
- This proves the collector and this snapshot passed structural/time-boundary checks. It does not prove strategy profitability, future data quality, or scanner correctness.
- H1 and D1 closed bars exist for all 44 symbols. A separate read-only D1/H1 scanner was merged in PR #74 (commit d004f0f); it has not yet been run against this artifact.
- Snapshot is a point-in-time data collection; intraday lookback windows are short (M1 7 calendar days; M5/M15/M30/H1/H2/H4/H8 and M10 30 days). W1/MN/QR/D1 use up to 5 years, subject to listing history and provider availability.
- Workflow artifact expires after 30 days; download it from the run above before expiry. Do not add the uncompressed JSON (~103 MB) to Git history.
- Keep the prospective holdout beginning 2026-11-20 sealed. Do not use these post-holdout data to tune or select the frozen strategy cohort.
