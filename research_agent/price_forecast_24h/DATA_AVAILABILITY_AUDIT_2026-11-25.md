# 24H Price Forecast — data availability audit (2026-11-25)

Status: **HISTORICAL H1 SAMPLE INSUFFICIENT FOR A CREDIBLE MODEL TEST.** Do not train, tune, or claim predictive skill from this archive.

## Scope and provenance

- Repository: `vkazarin763-cloud/moex-edge-fast1`.
- Isolated research branch: `research/price-forecast-24h-v1`.
- Audited artifact: `moex-edge-multi-timeframe-candles`.
- Workflow run: `44889538524`.
- Artifact ID: `14701243872`.
- Artifact created: `2026-11-21T09:29:36Z`; snapshot generated: `2026-11-21T09:25:51.184499Z`.
- Artifact expires: `2026-12-21T09:29:35Z`.
- Downloaded ZIP: `moex-edge-mtf-2026-11-21.zip`, 572,829 bytes; contained candle JSON (3,816,605 bytes) and validation JSON (10,234 bytes).
- The validation JSON reports `PASS`, 0 issues, 44 symbols.
- The collector workflow is scheduled for weekdays at 05:00 UTC, but the latest verifiable artifact inspected for this audit is the 2026-11-21 snapshot. The artifact is stale relative to the audit date.

## Observed history coverage

| Frame | Source | Symbols | Bars per symbol | Time coverage |
|---|---|---:|---:|---|
| H1 | Finam | 44/44 | 421–424 (median 424) | 2026-10-22 through 2026-11-21; 29 distinct calendar dates |
| D1 | MOEX ISS TQBR history | 44/44 | 249–253 (median 253) | 2025-11-21 through 2026-11-20 |

- H1 total: 18,648 completed bars.
- D1 total: 11,128 completed bars.
- H1 collector lookback is explicitly limited to 30 calendar days in `research_agent/multi_timeframe.py`.
- D1 history is approximately one year in this artifact; sufficient to calculate a trailing 60-session liquidity rank for the snapshot date, but not sufficient to provide point-in-time historical liquidity rankings over a long multi-year H1 evaluation.

## Data quality

The artifact's validator reported zero duplicate/non-monotonic timestamps, invalid OHLCV, and unclosed/future bars at the snapshot boundary. This validates the archived snapshot's structural integrity only; it does not prove future collection quality or model validity.

## Critical liquidity-field gap

The current MOEX ISS history adapter in `research_agent/moex_iss.py` parses `TRADEDATE`, `NUMTRADES`, OHLC, and `VOLUME`, but does not retain the official daily `VALUE` field. The archived D1 candles therefore cannot provide exact RUB turnover from the stored fields alone.

- Do not describe `close × volume` as official/exact traded turnover.
- Before selecting the top 10 liquid shares, extend the read-only collector/schema/validator to retain MOEX ISS `VALUE` and verify its units and completeness.
- If official `VALUE` is unavailable for any candidate, exclude that observation/security with a recorded reason rather than silently substituting a proxy.

## Feasibility decision

A 24-H1-bar forward target consumes roughly three MOEX trading sessions. The archived H1 sample covers only about 29 calendar dates, with a short intraday lookback. After constructing forward labels, chronological train/validation/test blocks, and a 24-bar purge/embargo, the remaining independent time span is too short for a credible multi-regime evaluation. Thousands of ticker-hour rows must not be mistaken for thousands of independent market observations.

**Decision: do not fit or tune forecasting models on this snapshot.** It is suitable for:
- testing the data parser and schema;
- validating the 24-bar target builder and no-lookahead rules;
- a small, explicitly labelled pipeline smoke test only.

It is not suitable for:
- claiming directional accuracy or return edge;
- selecting a production model;
- calibrating price prediction intervals;
- claiming robustness across market regimes.

## Recommended next step

Build a read-only prospective history collector on this research branch:

1. Each MOEX session, archive completed H1 candles for the frozen 44-symbol candidate pool and official D1 `VALUE` turnover.
2. Store immutable daily snapshots with UTC/Moscow timestamps, source provenance, schema version, checksum, and validation report.
3. Recompute the top-10 liquidity cohort once per week using only trailing 60 completed sessions of official `VALUE`.
4. Accumulate at least 6 months of clean H1 observations before the first meaningful model comparison; 12 months is preferable for regime diversity. Continue to reserve the final chronological block as an untouched test.
5. Keep all collection read-only and isolated. Do not touch production workflows, Finam execution, account/order endpoints, Telegram, secrets, or live-mode settings.

No model was trained, no signal generated, no workflow dispatched, and no production or trading configuration changed during this audit.
