# MOEX EDGE FAST

## Project handoff for another AI / maintainer

This repository contains an hourly MOEX signal scanner and a Finam execution workflow. This section is the operational handoff: read it before changing code or enabling/changing execution.

### Current operational configuration (workflow re-audited 2026-11-19)

- GitHub Actions workflow: `.github/workflows/moex-edge-fast.yml`
- Scheduled runs are configured hourly:
  - Weekdays: `0 4-20 * * 1-5` UTC (07:00–23:00 Moscow time).
  - Weekends: `0 7-16 * * 6,0` UTC (10:00–19:00 Moscow time).
- Manual workflow dispatch is enabled.
- The current workflow explicitly sets `FINAM_DRY_RUN: 'true'` and `FINAM_LIVE_TRADING_ENABLED: 'false'`; its executor step is labelled DRY RUN ONLY. This is a configuration-level safeguard, not evidence that a workflow run succeeded or that account state was checked.
- Required GitHub Actions secrets are still referenced for the dry-run/preflight integration: `FINAM_API_SECRET`, `FINAM_ACCOUNT_ID`. Optional notifications use `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Never print or commit secret values.
- The separate `.github/workflows/finam-executor.yml` also forces `FINAM_DRY_RUN: 'true'` in its execution step.
- Existing cron schedule is already configured. Do not create a second schedule or duplicate workflow.
- Do not change either live-execution flag or trigger a live workflow as part of research-agent development.

### Agreed trading/execution constraints

- Universe: exactly these 44 MOEX tickers:
  `AFKS, AFLT, ALRS, BSPB, CBOM, CHMF, CNRU, DOMRF, ENPG, FLOT, GAZP, GMKN, HEAD, IRAO, LKOH, MAGN, MDMG, MOEX, MTSS, NLMK, NVTK, OZON, PHOR, PLZL, POSI, RAGR, RENI, ROSN, RTKM, RUAL, SBER, SBERP, SNGS, SNGSP, SVCB, T, TATN, TATNP, TRNFP, UGLD, VKCO, VTBR, X5, YDEX`.
- Maximum open positions: 10.
- Maximum new orders per executor run: 1.
- Test sizing is configured to use one minimum trading lot (`TEST_MODE_MIN_VOLUME = True`).
- Exit monitoring is based on completed H1 candles:
  - LONG: stop 3% below entry; target 5% above entry.
  - SHORT: stop 3% above entry; target 5% below entry.
  - If stop and target are both touched in the same candle, stop takes priority.
- These exits are implemented by the H1 monitor and are not broker-native protective stop/target orders. The monitor sends a market exit on a later successful executor run after detecting a completed H1 candle crossing a level. Do not describe a position as exchange-protected by these percentage levels.
- Existing user instruction: scanner output should focus on trading signals, strategy, H1 confirmation and signal parameters; do not add capital allocation, investment sums or portfolio allocation recommendations unless explicitly requested.

### Main files and responsibilities

- `moex_edge_fast_33.py`: scans the 44-symbol universe and produces signals.
- `finam_executor.py`: reads signals, checks current account positions and active orders, enforces limits, deduplicates signals, and submits broker orders when live execution is enabled.
- `h1_position_monitor.py`: checks positions against completed H1 bars and initiates exits.
- `h1_percent_exit.py`: pure percentage exit-level and candle-touch logic; stop wins if both levels are touched in one candle.
- `finam_h1_data.py`: obtains and validates Finam H1 candle data; excludes incomplete/snapshot candles and validates OHLC/timestamps.
- `.github/workflows/moex-edge-fast.yml`: hourly and manual GitHub Actions workflow.

### Execution safeguards and known behavior

- Executor applies the 10-position cap and one-new-order-per-run cap.
- Signal deduplication uses a persistent journal. Preserve its concurrency protection and state persistence when modifying the workflow.
- H1 monitor fails closed when required H1 data is missing/stale or an active broker order makes monitoring ambiguous; this should block new entries rather than silently assume safety.
- Existing positions without a journal entry begin monitoring from the latest completed H1 candle; historical candles before monitoring starts are not replayed.
- If a broker order submission result is ambiguous, the executor is designed not to blindly repeat the POST.
- A prior Finam test encountered `OrderProtectionError` when Finam rejected SL/TP parameters. Treat broker-side SL/TP rejection as a serious unprotected-position condition. The current percentage H1 exit mechanism is separate from broker-native SL/TP.
- Do not disable fail-closed checks, deduplication, concurrency, position caps, or order caps merely to make a run pass.

### Verification status / what is not yet proven

- The percentage H1 exit implementation and related components passed the reported CI test run: 103 tests total (66 executor, 8 percentage exits, 6 MOEX H1, 8 Finam H1, 15 H1 monitor); compilation also passed.
- Workflow configuration was re-read from the default branch on 2026-11-18 and confirmed to contain both live-mode environment variables shown above.
- This does **not** prove that the current Finam credentials/account are valid, that the live workflow completed successfully, or that a broker order was accepted. Verify the first manual/cron run in GitHub Actions logs and, independently, confirm account positions/orders in Finam.
- Never claim that a live order was placed unless the executor logs and broker account confirm it.
- Secrets are not readable through this repository handoff; never request or expose their values in logs or documentation.

### Instructions for the next AI / maintainer

1. Read this handoff and inspect the current versions of the workflow and Python files before proposing edits; this document can become stale.
2. Check recent GitHub Actions runs and job logs before saying the system is running successfully.
3. For any code change, add/update tests, run the full relevant test suite, and report actual results only.
4. Preserve the user's current operating constraints unless the user explicitly changes them.
5. Re-read the actual workflow before every operational claim. As last audited on 2026-11-19, the scheduled scanner workflow sets DRY RUN true and LIVE TRADING false; a later workflow change invalidates this statement.


### Autonomous research pipeline v2 (draft PR #150)

- `research_agent/v2/pipeline.py` connects hypothesis discovery, next-open execution, moving-block bootstrap inference, and Holm family-wise correction.
- The split is explicit: thresholds and entry hypotheses are generated only from the formation prefix; the evaluator receives only validation bars and feature rows. Validation features must themselves be causal (current/past only).
- The exit rule is supplied and fixed by the caller before validation. The pipeline does not optimize or select exits on validation results.
- All generated hypotheses remain in the registered Holm family. Candidates with too few closed trades, or an invalid block length for their sample, receive a conservative p=1 placeholder for correction and are separately labelled `INSUFFICIENT_DATA`; p=1 is not represented as a measured p-value.
- A result can only be labelled `CANDIDATE_FOR_WALK_FORWARD` when its bootstrap interval is positive and its null is rejected after Holm correction. This is not approval or a live signal; a separate walk-forward stage and untouched final holdout are still required.
- This is an orchestration layer, not yet an autonomous end-to-end market-data job. No real MOEX performance is claimed until validated real OHLCV data is supplied and processed.
- Focused tests: `tests/test_research_agent_v2_pipeline.py`.


### Real MOEX D1 data connection (pre-holdout only)

- `research_agent/v2/moex_dataset.py` loads the matching multi-timeframe collector JSON and validation JSON. It fails closed unless the collector validation is PASS with zero issues and provenance timestamps match.
- Only native `MOEX ISS TQBR history` D1 bars strictly before `2026-11-20` are returned. OHLCV fields on/after the holdout boundary are not parsed, used for features, generated hypotheses, or candidate selection.
- `research_agent/v2/moex_runner.py` extracts causal OHLCV features, runs the v2 pipeline per symbol, then applies one global Holm correction across the complete generated family across all symbols.
- The current integration baseline uses a predeclared candle-body reversal exit (LONG exits on a non-positive body; SHORT exits on a non-negative body). Exit discovery is not yet autonomous; this fixed exit is only an explicit baseline and is not optimized on validation data.
- The current frozen collector artifact contains 44 symbols and native D1 history. The prospective holdout from 2026-11-20 remains sealed. Intraday H1 data is not used in this D1 discovery run.
- `.github/workflows/research-agent-v2-moex-d1.yml` runs automatically after a successful read-only multi-timeframe collector workflow, downloads that exact run's artifact, and uploads only the research JSON report. It does not use `workflow_dispatch`, broker credentials, account endpoints, or order endpoints.
- The default research assumptions are 70/30 chronological formation/validation, 20 generated hypotheses per symbol, 19,999 bootstrap resamples, 5-trade block length, 0.08% commission and 0.05% slippage per side. These are explicit research assumptions, not a verified broker tariff or measured execution slippage.
- Results can only identify candidates for a later walk-forward stage. They do not constitute strategy approval, live signals, or evidence of profitability.
- Focused tests: `tests/test_research_agent_v2_moex_dataset.py`.
