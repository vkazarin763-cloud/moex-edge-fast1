# MOEX EDGE — AI research handoff (current as of 2026-11-23)

> **Priority note for the next AI:** this section is the latest state of the AI research-team pilot. Older sections below describe other workstreams and historical executor/scanner states; do not treat them as the latest state of this research branch.

## Current repository / safety boundaries
- Research repository: https://github.com/vkazarin763-cloud/moex-edge-fast1
- Active branch: `feature/openrouter-primary-groq-fallback`
- PR #163: https://github.com/vkazarin763-cloud/moex-edge-fast1/pull/163
- PR #163 is OPEN and NOT MERGED. Do not merge without the user's explicit instruction.
- Production repository `vkazarin763-cloud/moex-edge` has not been changed by this work.
- This AI research pilot is read-only: no broker API, no orders, no Telegram, no production-scanner writes.
- Start with free services. Do not propose paid model/API upgrades until the free pilot demonstrates a concrete limitation worth paying to solve.
- Deterministic Python computes market data, indicators, tests, and strategy status. LLMs provide commentary/critique only; never treat AI commentary as a signal or backtest.
- Never invent market data, signals, prices, PnL, or performance results. Preserve all data-quality caveats.

## Latest successful real-data AI research run
- GitHub Actions run: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45108741043
- Run ID: `45108741043`; completed successfully on 2026-11-23.
- Branch SHA used by the run: `d3324753c78c87d6242456e4bc064d326aab12b2`.
- Artifact: `ai-research-report-45108741043` (artifact ID `14787909357`, expires 2026-12-07).
- Files: `research_report.json`, `strategy_registry.json`, `ai_commentary.json`.
- Workflow stages all succeeded: compile/offline tests, date resolution, MOEX ISS research, OpenRouter key check, four-agent commentary, artifact upload.
- Inputs: TQBR daily bars, tickers SBER, GAZP, LKOH, NVTK, MOEX; requested dates 2023-11-20 through 2026-11-20. Five instruments analyzed, no history-fetch errors. Approximately 765 research bars per ticker.
- Report audit: `INDEPENDENT_VALIDATION_INCOMPLETE`; 55 structural checks, 0 errors, 20 walk-forward folds and 25 cost candidates checked. This is not a data-provenance certification.
- Audit warnings: one raw-candle/TQBR reconciliation mismatched day each for SBER, GAZP and MOEX; 9 calendar-gap candidates per ticker; exchange calendar not independently verified. Experiment lab was intentionally skipped. These are unresolved research blockers.
- Holdout starts 2026-11-20, and the source report ends 2026-11-20. Each ticker has only one holdout bar and zero closed prospective trades. No prospective statistical conclusion is available.

## Authoritative directional strategy registry
- Registry version: `development-registry-v1`; stage `DEVELOPMENT_ONLY_NOT_PRODUCTION_APPROVAL`.
- 50 rows = 5 tickers × 5 strategies × 2 directions (LONG and SHORT).
- Summary: PASS 0, REJECT 0, INSUFFICIENT_DATA 50.
- All rows have `eligible_for_shadow_scanner=false`.
- Selection policy: at least 30 closed trades; all 4 walk-forward folds must each meet at least 5 trades; positive average net return; profit factor > 1; doubled-cost screen must pass. LONG and SHORT are evaluated independently.
- Example: GAZP Donchian20 LONG has 17 trades and 2/4 adequately sampled folds; it is INSUFFICIENT_DATA, not approved. Never promote descriptive aggregates over this registry.
- Baseline execution assumptions: fee 0.001 and slippage 0.0005 per side; stop 3%, target 6%, max bars 120. Doubled-cost case: fee 0.002 and slippage 0.001 per side. These are research assumptions, not guaranteed live execution costs.

## Important correction: 25 vs 50 multiple-testing counts
The AI reviewer/coordinator flagged family_size=25 versus 50 registry rows as a possible mismatch. Inspection of the source implementation shows these are **different hypothesis families**, not a demonstrated calculation defect:
- 50 is the **development selection registry**: ticker × strategy × direction (LONG/SHORT).
- 25 is the **prospective holdout Holm family**: ticker × frozen entry strategy (5 tickers × 5 strategies). The current `prospective_holdout_report()` does not split prospective hypotheses into LONG and SHORT.
- The holdout correction currently has 0 eligible tests because there are no closed prospective trades. The correction has not produced any statistical pass.
- Do not compare the Holm family size directly with the development registry row count.
- Code changes now make this scope explicit in `research_agent/validation.py`, the CLI report, and AI prompts. The CLI derives family size from the registered frozen strategy set rather than a magic literal.
- Added regression coverage for the family scope and AI instruction. The CI run for the latest code is pending/needs verification (see below).

## AI providers and agents
- Primary: OpenRouter model `openrouter/free`.
- Model fallback: `nvidia/nemotron-3-ultra-550b-a55b:free`, also routed through OpenRouter. This is a model fallback, NOT an independent provider failover.
- Groq direct API previously failed with HTTP 403 / code 1010. Do not claim independent Groq failover works.
- In run #45108741043, primary OpenRouter returned empty content twice due to reasoning-token exhaustion (finish_reason=length; 4096 and 3941 reasoning tokens). Both requests successfully fell back to Nemotron. The other two calls succeeded on OpenRouter.
- Four roles completed: market analyst, strategy researcher, skeptical reviewer, coordinator. Commentary status is `AI_COMMENTARY_ONLY`.
- The agents received the complete 50-row directional registry and correctly kept every row INSUFFICIENT_DATA. The coordinator did not promote GAZP LONG. They accurately reported cost assumptions and data caveats.
- The reviewer did incorrectly interpret the 25-vs-50 difference as a discrepancy; this has now been diagnosed and prompts/code metadata are being corrected.

## Latest code/test history
- Previous overflow fix: commit `9a69fee476b3e1fa48de494aaedb1c6abe352c20` (progressive compaction preserves all decision-critical registry/ticker evidence).
- Overflow regression test: `d3324753c78c87d6242456e4bc064d326aab12b2`.
- CI run for that version: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45108596507 — 15/15 AI-team tests passed.
- Holm-scope clarification and regression tests were added in sequential commits:
  - `d076562bf92c1562edddb6ac095fe815b9d59e8c` — explicit holdout family metadata.
  - `c62b305ccd8cbc143fa1679006c664491a6a1708` — remove hard-coded family size in CLI.
  - `20b9100c8b6a17dfc48e65212b86302ecae50a85` — AI prompt and compact evidence scope clarification.
  - `b29a33af564be97e767a5cf2eeeafda142c0ebea` — holdout family tests.
  - `039cb1134fb78954d76309e13f2eccb380a2dec4` — AI prompt test.
  - `2289d57c9d6125bcae1840120cb485ad04ec9cda` — CI now runs both AI-team and holdout tests.
- Latest CI workflow run: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45196047412 — success, 58 tests, including official-calendar annotations and session mapping audit tests. SHA `7ff991bacacd4df942ffb95de506a906f1f42eb6`.

## Next actions (continue autonomously in this order)
1. CI is now green: run `45196047412`, 58 tests. Do not reopen the same completed check unless code changes.
2. The three raw volume mismatches are now traced to the raw `candles.json` volume field; OHLC and VALUE match total-session history. Research D1 input uses TQBR history VOLUME. Keep this as a disclosed raw-source caveat.
3. All 9 observed calendar gaps have official MOEX schedule annotations in `research_agent/quality.py`; global calendar verification remains false. Current code passes session mapping diagnostics into `audit_tqbr_history`, fixing the old false classification of mapped weekend fragments.
4. Next required verification: rerun Manual AI Research Team on branch `feature/openrouter-primary-groq-fallback` with the same date/ticker/provider parameters. This must be manually dispatched by the user through GitHub Actions; no workflow-dispatch connector action is available here. Inspect new artifact to confirm mapped weekend fragments are excluded from same-date missing-history list and the three volume mismatches remain isolated.
5. Keep `INDEPENDENT_VALIDATION_INCOMPLETE` until the new real-data artifact confirms all warnings and the remaining data-provenance caveats are understood.
6. Keep PR #163 open/unmerged. Do not touch production repository, broker integration, live trading, Telegram, or paid services.

## User working preferences
- Work in practical increments; minimize requests for manual user steps.
- Explain results in plain Russian.
- User expects independent verification and honest limitations.
- The goal is to prove whether the free agent workflow is useful before paying for faster models.


## 2026-11-23 — follow-up audit of calendar gaps and raw-volume mismatches

### Official MOEX calendar review
The 9 daily-history gap windows were checked against official MOEX schedules. They are explained by published market closures and/or additional weekend/holiday sessions that are part of the next ordinary trading date; they should not be treated as evidence of missing TQBR D1 bars:
- 2023-12-29 → 2024-01-03: 1–2 Jan 2024 were closed. MOEX 2024 holiday schedule: https://www.moex.com/n64121
- 2024-02-22 → 2024-02-26: 23 Feb 2024 was closed. Same official 2024 schedule.
- 2024-03-07 → 2024-03-11: 8 Mar 2024 was closed. Same official 2024 schedule.
- 2024-12-30 → 2025-01-03: 31 Dec 2024 and 1–2 Jan 2025 were closed; 3 Jan was an open holiday session. MOEX schedules: https://www.moex.com/n75066 and https://www.moex.com/n73701
- 2025-05-08 → 2025-05-12: 9 May was closed; 10–11 May were additional weekend sessions. Weekend sessions from 2025-03-01 are rolled into the next ordinary trading day: https://www.moex.com/n77967 and https://www.moex.com/n77931
- 2025-12-30 → 2026-01-05: 31 Dec 2025 and 1–4 Jan 2026 were closed; 5 Jan 2026 was an open holiday session. Sources: https://www.moex.com/n73701 and https://www.moex.com/n94207
- 2026-02-20 → 2026-02-24: 21–22 Feb weekend sessions and 23 Feb special session are part of the next ordinary trading date. Sources: https://www.moex.com/n95564 and https://www.moex.com/n96571
- 2026-04-30 → 2026-05-04: 1 May special session and 2–3 May weekend sessions are rolled into the next ordinary trading date. Same 2026 sources.
- 2026-06-11 → 2026-06-15: 12 June special session and 13–14 June weekend sessions are rolled into the next ordinary trading date. Same 2026 sources.
- Therefore, these 9 gap windows are manually explained by official schedules. The current pipeline still reports `exchange_calendar_verified=false` because this manual research has not yet been encoded as a reproducible in-pipeline calendar audit. Do not silently flip that flag or claim the code now verifies the calendar.

### Exact raw-candle vs TQBR history checks
The three `session_date_mapping` mismatches were queried directly from MOEX ISS. For each, daily candle OHLC and turnover VALUE match the TQBR total-history row exactly; only VOLUME differs. This narrows the discrepancy but does not explain it:
- SBER 2025-08-01: candle VOLUME 25,320,049 vs history VOLUME 18,473,506 (difference +6,846,543; +37.06% vs history). OHLC and VALUE match. TQBR history sessions 0/1/2 volumes were 3,311,286 + 11,681,020 + 3,481,200 = 18,473,506.
  - Candle: https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/SBER/candles.json?from=2025-08-01&till=2025-08-01&interval=24&iss.meta=off
  - History total: https://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities/SBER.json?from=2025-08-01&till=2025-08-01&tradingsession=3&iss.meta=off
- GAZP 2025-10-27: candle VOLUME 44,070,553 vs history VOLUME 46,407,070 (difference -2,336,517; -5.03%). OHLC and VALUE match.
  - Candle: https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/GAZP/candles.json?from=2025-10-27&till=2025-10-27&interval=24&iss.meta=off
  - History total: https://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities/GAZP.json?from=2025-10-27&till=2025-10-27&tradingsession=3&iss.meta=off
- MOEX 2025-10-27: candle VOLUME 5,370,130 vs history VOLUME 5,826,160 (difference -456,030; -7.83%). OHLC and VALUE match.
  - Candle: https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/MOEX/candles.json?from=2025-10-27&till=2025-10-27&interval=24&iss.meta=off
  - History total: https://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities/MOEX.json?from=2025-10-27&till=2025-10-27&tradingsession=3&iss.meta=off
- Root cause is UNKNOWN. Do not classify these as harmless. Strategy inputs are built from per-security TQBR history, not the raw candle volume field, but raw-to-history provenance remains incomplete until this field discrepancy is explained or explicitly handled with evidence.

### Session-aware crosscheck code change
- `research_agent/quality.py` now accepts the session-mapping diagnostic in `audit_tqbr_history()`. It excludes weekend calendar-date fragments from same-date “no history row” warnings only if the session mapper confirms every weekend fragment mapped and zero weekend fragments remained unmapped.
- The audit records `mapped_weekend_fragments_without_same_date_history` and `weekend_fragments_excluded_from_same_date_crosscheck`. It deliberately keeps `exchange_calendar_verified=false`; mapping is not proof of an exchange-wide calendar.
- CLI passes `session_date_mapping_diagnostics` into this crosscheck.
- Added tests for fully mapped and unmapped weekend fragments. Latest CI run for these changes: check https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45110066248 (was in progress at the time of this update).
- This change addresses the false same-date weekend-fragment warning only. It does NOT clear the three raw VOLUME mismatches or certify the official calendar in code.


## Verification after the latest code changes
- CI run #45110066248 completed SUCCESS on commit `e77e82bae0802af6e359844c9cbd6a1045fd3060`: compile passed; 40 tests passed across `tests.test_research_ai_team`, `tests.test_research_holdout`, and `tests.test_research_quality`. New tests for Holm family scope and mapped/unmapped weekend fragments passed.
  - https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45110066248
- CI run #45110078016 completed SUCCESS on commit `c7df6202c40ae1a07901ed18fcf2235e63e88b27`, validating the aligned path filters.
  - https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45110078016
- Current branch HEAD at this handoff update: `f183eacc95f933bd9e6645ff0d8ccb463675c8c7`. PR #163 remains open and unmerged.
- The research workflow now includes a branch-push trigger for relevant research code/tests, retains manual dispatch, and runs all three offline test modules before any market-data/AI work. Push trigger is VERIFIED: run #45110189920 started automatically from push event on SHA `f183eacc95f933bd9e6645ff0d8ccb463675c8c7`; offline tests, date resolution, MOEX research generation and OpenRouter key check passed. Four-agent commentary was still running at the last check. Do not claim end-to-end completion until the run finishes and its artifact is inspected.
- Required next verification: monitor run #45110189920 to completion, download its artifact, and check `tqbr_history_crosscheck`, `session_date_mapping`, 50-row registry, AI roles and costs. If the run fails, diagnose and fix on this feature branch; the push trigger should rerun after a relevant code change.


### Deeper volume-field diagnosis (MOEX ISS cross-check)
A further independent cross-check was performed on the same three mismatch dates:
- The 18 hourly TQBR candle volumes sum exactly to the daily candle VOLUME for each security/date. Hourly VALUE sums also match the daily candle VALUE. Thus daily and hourly candle endpoints share the same volume series on these dates.
- However, the candle VALUE / candle VOLUME implied average price is outside the daily OHLC range, which is mathematically inconsistent if VOLUME is share quantity:
  - SBER: candle implied average 222.75 RUB vs daily low/high 302.89–307.50; history implied average 305.30 RUB.
  - GAZP: candle implied average 121.94 RUB vs low/high 115.10–116.98; history implied average 115.80 RUB.
  - MOEX: candle implied average 176.70 RUB vs low/high 161.27–166.50; history implied average 162.87 RUB.
- The history VOLUME is therefore internally consistent with turnover VALUE and OHLC on all three mismatched dates; the candle VOLUME is the field that fails this basic consistency check. This points toward an anomaly in the candle volume series rather than the TQBR history volume, but the official field semantics/root cause have not been fully certified.
- Practical rule: keep TQBR history as the current model-input source for volume; do not replace it with candle/hourly volume on these dates. Add an automated turnover-implied-average-price check before any source substitution. Because strategies use relative volume, any future volume-source change requires a fresh backtest/sensitivity comparison; do not patch three bars silently.
- Hourly cross-check endpoints were queried for SBER 2025-08-01, GAZP 2025-10-27, MOEX 2025-10-27 with `interval=60`; each returned 18 hourly candles. Example URL pattern: `https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{TICKER}/candles.json?from={DATE}&till={DATE}&interval=60&iss.meta=off`.


## 2026-11-23 — latest session audit correction and CI
- Artifact from run #45110189920 showed `tqbr_history_crosscheck=CROSSCHECK_INCONCLUSIVE` for all five tickers, not because of unmapped weekend candles (those were all mapped), but because four official weekday additional-session dates remained in `candles_without_history_record`: 2026-02-23, 2026-05-01, 2026-06-12, 2026-11-04. The session mapper already reported 4/4 weekday additional-session candles mapped for each ticker.
- Code now exports `weekday_additional_session_dates` and `mapped_weekday_additional_session_dates` from `session_date_mapping`. `audit_tqbr_history` excludes those weekday dates from same-date missing-row warnings only when all such fragments are mapped and zero remain unmapped, just as it already does for weekends. It keeps `exchange_calendar_verified=false`; this is a session-mapping crosscheck, not a full exchange-calendar certification.
- AI compact evidence now carries structured per-ticker `session_date_mapping` mismatch examples and `tqbr_history_crosscheck` counts/flags, including both weekend and weekday additional-session handling. This makes the AI agents aware of exact data-quality issues instead of only a high-level status.
- Regression CI run #45110952751 completed SUCCESS on commit `6bc1ed7ad2fbfb40f11a6478fe4e24e6acb6b7b8`: compile passed and 56 tests passed across AI-team, holdout, quality and MOEX session-mapping modules.
  - https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45110952751
- Automatic full research run #45110952761 started on the same code commit. At the time of this note, offline tests and date resolution passed; MOEX data generation was in progress. Inspect the final artifact before concluding the weekday crosscheck is clean or the AI commentary completed.
  - https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45110952761
- The preceding run #45110189920 failed only at AI commentary: primary OpenRouter returned empty content after 4,347 reasoning tokens; Nemotron fallback via OpenRouter timed out at 60 seconds. Its deterministic MOEX report and registry were successfully generated and uploaded. The artifact contains 50 registry rows (0 PASS, 0 REJECT, 50 INSUFFICIENT_DATA). This is a model availability/timeout failure, not a deterministic data-generation failure.


## 2026-11-23 — final compact-evidence optimization in progress
- Run #45110952761 generated the corrected research report, including clean `tqbr_history_crosscheck` statuses for all five tickers, but AI commentary stopped before provider calls because compact evidence measured 33,146 characters (30,000 limit).
- First optimization deduplicated the 25 unique registry reason strings into a code map (R1…Rn), while each of the 50 strategy rows retains its reason-code list. The exact original reason text remains available in `strategy_registry.reason_codes`; metrics/statuses/eligibility remain intact.
- Second optimization stores identical per-ticker execution assumptions once in `cost_model_profiles` (C1…Cn), while `cost_model_by_ticker` maps each ticker to its profile. Baseline and doubled fee/slippage/stop/target/max-bars values are retained exactly.
- Per-ticker session mismatch examples are compacted to date plus mismatched field values; structured session and history crosscheck evidence remains included.
- The AI-team CI run #45111581132 passed compile + 56 tests on commit `b88304485aba330d49c1e8a7978ac5c04105ef3c`.
  - https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45111581132
- Automatic full research run #45111581019 is now running on the same commit. Offline tests and date resolution passed; MOEX research generation was in progress at the time of this note. The next check is whether compact evidence is below 30,000 and whether all four AI roles finish.
  - https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45111581019

## 2026-11-23 follow-up: raw volume discrepancies and calendar-gap audit
- Retrieved the original MOEX ISS `candles.json` rows and `/history/...json?tradingsession=3` total-session rows directly for the flagged dates.
- Three discrepancies are confined to the raw daily-candle `volume` field; OHLC and `value` match the total-session history:
  - SBER 2025-08-01: candles volume 25,320,049 vs total-history VOLUME 18,473,506; both VALUE 5,640,029,361.96; OHLC matches.
  - GAZP 2025-10-27: candles volume 44,070,553 vs total-history VOLUME 46,407,070; both VALUE 5,374,154,168.40; OHLC matches.
  - MOEX 2025-10-27: candles volume 5,370,130 vs total-history VOLUME 5,826,160; both VALUE 948,900,010.30; OHLC matches.
- The deterministic research D1 input is built from per-security TQBR history records (`build_trading_day_candles(bounded_history_records,...)`), not the raw `candles.json` volume. Thus the strategy's volume input is history VOLUME; raw candle volume mismatch remains an independent source-reconciliation caveat and must not be silently overwritten.
- The artifact from run #45108741043 predates the current CLI fix that passes `session_date_mapping_diagnostics` into `audit_tqbr_history`. Its `candles_without_history_record` list incorrectly included 134–138 mapped weekend fragments. Current branch CLI now passes the mapping diagnostics; tests already cover mapped/unmapped weekend and weekday additional-session behavior. A new real-data rerun is still needed to confirm the corrected report.
- Official MOEX calendar review of all 9 observed D1 gap candidates:
  - 2023-12-29 → 2024-01-03: 2024-01-01/02 official no-trade days.
  - 2024-02-22 → 2024-02-26: 2024-02-23 official no-trade day.
  - 2024-03-07 → 2024-03-11: 2024-03-08 official no-trade day.
  - 2024-12-30 → 2025-01-03: 2024-12-31 and 2025-01-01/02 no-trade days.
  - 2025-05-08 → 2025-05-12: 2025-05-09 no-trade; 10–11 May weekend sessions carried into the next trading day.
  - 2025-12-30 → 2026-01-05: 2025-12-31 and 2026-01-01..04 no-trade.
  - 2026-02-20 → 2026-02-24: Feb 21–23 additional sessions carried to Feb 24.
  - 2026-04-30 → 2026-05-04: May 1–3 additional sessions carried to May 4.
  - 2026-06-11 → 2026-06-15: June 12–14 additional sessions carried to June 15.
- Code now annotates these exact gap pairs in `research_agent/quality.py` with official MOEX source URLs, while keeping the global `exchange_calendar_verified=false`: this is a targeted review of observed candidates, not certification of every date in the full sample.
- CI expanded to run AI-team, holdout, and research-quality tests. Latest run #45196020929 is in progress and must be checked before claiming success.
- Official source pages: https://www.moex.com/n64121 (2024 holidays); https://www.moex.com/n73701 (2025 holidays); https://www.moex.com/n77967 (2025 weekend sessions); https://www.moex.com/n89969 (May 2025); https://www.moex.com/n94172 (2026 holidays); https://www.moex.com/n95564 (2026 weekend sessions); https://www.moex.com/n96571 (2026 Feb/May/June holiday sessions).

