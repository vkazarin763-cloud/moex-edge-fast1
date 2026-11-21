# MOEX EDGE — project handoff

**Snapshot date:** 2026-11-21  
**Repository:** https://github.com/vkazarin763-cloud/moex-edge-fast1  
**Default branch at snapshot:** `main`  
**Main SHA at snapshot:** `b314dacf6b62989266347e638f700427b98ff505`

This document is the durable handoff for another AI or developer. Treat it as a project-state snapshot, not as proof that workflow runs mentioned below are still current. Recheck GitHub before acting.

## 1. Mission and working style

MOEX EDGE is an **Autonomous Research Agent**, not merely a signal scanner. The scanner is one component. The intended system collects and validates MOEX market data, develops hypotheses, tests strategies with realistic execution assumptions, performs walk-forward/out-of-sample validation, audits results independently, and reports evidence without overstating it.

The user expects autonomous progress with minimal manual work. When asked to continue, perform safe repository work rather than only describing plans. Give concise, factual updates. Clearly distinguish verified results, hypotheses, and planned work.

## 2. Mandatory safety and repository boundaries

- Work only in `vkazarin763-cloud/moex-edge-fast1`.
- Never modify the production repository `vkazarin763-cloud/moex-edge-fast`.
- Research agent is read-only. Never submit live orders, call broker order endpoints, enable live trading, or turn research into execution.
- Never request, print, expose, or commit `FINAM_API_TOKEN` or any other secret.
- Do not bypass logins, CAPTCHAs, API limits, or access controls.
- Do not use `workflow_dispatch`.
- Do not modify these protected files:
  - `moex_edge_fast1.py`
  - `finam_executor.py`
  - `futures_scanner.py`
  - `futures_executor.py`
  - `ai_agent.py`
  - `ai_trainer.py`
  - `ai_portfolio.json`
  - `ai_weights.json`
- Legacy `ai_agent.py`, `ai_trainer.py`, `ai_weights.json`, and `ai_portfolio.json` belong to a separate virtual-trading experiment. Do not reset or repurpose them.
- Legacy workflows are independent. `moex-edge-fast.yml` runs Finam executor with `FINAM_DRY_RUN=true` and `FINAM_LIVE_TRADING_ENABLED=false`; `ai-agent.yml` may update `ai_portfolio.json`. Do not modify these workflows.
- Scanner output must not contain capital, position sizing, portfolio allocation, or investment amounts unless the user explicitly asks. Show signals, direction, strategy, H1 confirmation, and relevant signal parameters only.
- User earlier requested LONG-only in some research branches, but the current frozen cohort is LONG+SHORT. Do not change the frozen cohort without explicit permission.
- User requires real data only. Never invent prices, signals, metrics, trades, or backtest results. Do not claim profitability without valid completed tests.

## 3. Frozen research protocol — do not alter

- Holdout start: **2026-11-20**. Holdout is strictly prospective and must never be used for tuning.
- Frozen cohort: `v1-frozen-2026-11-19`.
- Universe: 44 tickers:
  `AFKS,AFLT,ALRS,BSPB,CBOM,CHMF,CNRU,DOMRF,ENPG,FLOT,GAZP,GMKN,HEAD,IRAO,LKOH,MAGN,MDMG,MOEX,MTSS,NLMK,NVTK,OZON,PHOR,PLZL,POSI,RAGR,RENI,ROSN,RTKM,RUAL,SBER,SBERP,SNGS,SNGSP,SVCB,T,TATN,TATNP,TRNFP,UGLD,VKCO,VTBR,X5,YDEX`
- Five frozen entry strategies:
  1. Donchian20 breakout
  2. EMA20x50 cross
  3. RSI14 trend 50 crossing
  4. MACD12x26 crossover
  5. Keltner20x2ATR breakout
- Statistical controls: minimum 30 trades; Newey-West HAC; moving-block bootstrap confidence intervals; Holm-Bonferroni correction across 220 symbol/strategy hypotheses.
- Execution simulation: signal at close, entry next open; stop-first when stop and target both hit in one bar; stop gaps execute at open; target gaps execute at target; two-sided commissions and slippage; non-overlapping trades.
- Frozen exits: 3% stop, 6% target, maximum 120 daily bars. Commission 0.1% per side; slippage 0.05% per side.
- Do not modify frozen exit or entry settings. Alternative exits/entries belong in separate exploratory cohorts.
- New hypotheses must not contaminate the frozen cohort.
- No profitability or statistical-significance claim until adequate prospective samples and valid tests exist.

## 4. Research history and safeguards

Previously merged work (verify actual PR/commit state if needed):
- **PR #91** — immutable experiment execution configurations; full BacktestConfig validation and tamper/NaN tests. PR head `f15fb6e0e4626032ad372bde9fdd01a0571746e1`; reported squash merge `fc034fa614f5c18d15c12c1ceb73fd385805e539`.
- **PR #92** — independent reference replay for simulator execution audit. Head `e3f1fa83e0b75d39a74b7a7bfe595331484764e4c9` (verify exact SHA from GitHub if relying on it); reported merge `1fe0d19070222791fc185494915458188d3d21c3`.
- **PR #93** — require independent execution replay in Research Lab trials. Head `600581c9b15de6e019392fda499f42954166798d`; reported merge `f3aa7c18e1ee96df083d7ca05550d72e883eb1fb`.
- **PR #94** — independent replay of frozen entry signal formulas in `research_agent/reference_signals.py`; parity, tamper, future-bar invariance, warmup and last-bar guard tests. Head `7b8e5115a8cb35ed35392cc6aa9bb81b4ca2792e`. Known limitation: replay compares signal index/direction/strategy, not every metadata field; indicator initialization should be compared with core implementation.
- **PR #99** — map official MOEX 2026 weekday holiday sessions. Diagnostic only; official TQBR D1 bars remain model input. Reported merge `7db4f8cb0ba6cd731007655fdb06f7d341367c52`.
- **PR #103** — corporate-action price-basis audit for GMKN, TRNFP, VTBR, PLZL, T in `research_agent/corporate_actions.py`. Classifications include `MATCHES_KNOWN_PRE_EVENT_PRICE_BASIS`, `NO_KNOWN_CORPORATE_ACTION_REFERENCE`, and `UNEXPLAINED_PRICE_SCALE_DIFFERENCE`. No automatic OHLCV adjustment. Branch `research/corporate-action-price-basis-audit-v2`; head `b4bcc5b4e998668880c2a054c9fcca63352782dc`. Caveat: factor match alone does not prove full vendor series adjustment correctness; source/event terms require independent confirmation.
- **PR #104** — complete raw session reconciliation diagnostics in `research_agent/session_mapping.py`: `mapped_raw_candles`, `unassigned_reason_counts`, `mismatch_reason_counts`, `mismatch_field_counts` for OHLCV; validators check count reconciliation, totals, nonnegative counts and exact field keys. Synthetic fixtures were corrected during CI. Reported merged; verify actual merge state and SHA before relying on that claim.
- **PR #105** — latest main commit triggers full research after session-mapping changes. Snapshot main SHA: `691d2a1876460e0f5af5b80dac046e4da6b1d12d`.

Only merge code PRs after both mandatory checks — **Research Agent Safety Tests** and **Finam Executor Safety Tests** — have completed successfully on the exact current PR head SHA. If head SHA changes, recheck both. If CI fails, inspect logs, fix, and wait for fresh checks. The user authorized autonomous safe merges under this rule. Never assume a merge succeeded without GitHub confirmation.

## 5. Historical evidence — do not overstate

Historical research run `44797994665`, artifact `14693740145`, generated 2026-11-21 05:08 UTC. Range 2023-11-20 through 2026-11-20; native per-security MOEX ISS TQBR D1 model data; 44/44 tickers; 31,449 model daily candles.

Development folds:
1. 2024-09-03 to 2025-03-24: 31 eligible, 947 trades.
2. 2025-03-24 to 2025-10-10: 37 eligible, 1,127 trades.
3. 2025-10-10 to 2026-05-05: 40 eligible, 923 trades.
4. 2026-05-05 to pre-holdout boundary: 43 eligible, 1,323 trades.

Each ticker had only one holdout bar on 2026-11-20 (44 bars total). All 220 symbol/strategy holdout tests were `INSUFFICIENT_PROSPECTIVE_SAMPLE`, with zero closed trades; no HAC/bootstrap/Holm p-values were produced.

17 preliminary unadjusted development combinations passed an initial screen (10 Donchian, 7 MACD); all 17 failed double-cost stress; zero survivors.

Development portfolio aggregates (historical diagnostic only):
- cap 5: return -18.81%, max drawdown -40.12%, 955 trades, win rate 35.08%, PF 0.946, utilization 95.48%.
- cap 7: return -12.19%, max drawdown -34.86%, 1,277 trades, win rate 35.55%, PF 0.964, utilization 94.04%.
- cap 10: return -12.09%, max drawdown -34.72%, 1,673 trades, win rate 35.62%, PF 0.964, utilization 91.33%.

Interpretation: evidence is currently negative/inconclusive. These development results are not proof of future performance and are not a profitability claim.

## 6. Data-quality and calendar caveats

- All 44 symbols had status `VALID_WITH_CAVEATS`.
- History crosscheck: `CROSSCHECK_INCONCLUSIVE`.
- Before the expanded PR #104 diagnostics, raw calendar reconciliation showed 1,237 trading-day mismatches, 419 unassigned raw candles, and 5,711 unverified raw weekend bars.
- Model input remains native TQBR history; raw fragments are diagnostic only. Do not inject unverified raw fragments into model input.
- Do not claim calendar reconciliation is complete. MTF validator PASS does not clear raw calendar caveats.

Official 2026 weekday additional-session mappings previously used:
- 2026-02-23 → 2026-02-24
- 2026-05-01 → 2026-05-04
- 2026-06-12 → 2026-06-15
- 2026-11-04 → 2026-11-05
Reference: https://www.moex.com/n96571

Corporate-action references:
- GMKN split 100:1 effective 2024-04-04.
- TRNFP split 1:100 effective 2024-02-21.
- VTBR consolidation 5000:1 effective 2024-07-15.
- PLZL split 1:10; trading resumed 2025-03-27.
- T (T-Technologies) 10:1 split/conversion; trading resumed 2026-04-17.
Never assume the vendor price-basis direction from the ratio alone; the audit considers both directions.

## 7. Workflow snapshot at handoff time — must recheck

At approximately 08:45 UTC on 2026-11-21, main was at `691d2a1876460e0f5af5b80dac046e4da6b1d12d`.

- Autonomous Research run **44886351505**: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/44886351505 — status was `in_progress`; job `research` id `136792364504`. Setup, checkout, Python setup and date-range validation had passed; full research step was still running; report upload was pending.
- Hourly scanner run **44886365415**: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/44886365415 — status was `in_progress`; job `scan_and_execute` id `136792406981`.
- AI Virtual Agent run **44886361352** was a separate legacy experiment; do not confuse it with Research Agent or modify its workflow.

Other previous validation:
- MTF validation run `44866432461`: success, validator PASS, issue_count 0; 44 symbols, 13 feeds, 787,929 complete candles; D1/H1 44/44; no duplicate/invalid OHLC/negative volume/future incomplete bars/chronology issues; 826 D1 zero-trade rows excluded, 0 snapshot-true excluded.
- Scanner run `44868142437`: success, read-only; as-of 2026-11-21 04:30 UTC; 44-symbol universe; 40 signals, 0 skipped, all 40 SHORT across 27 tickers; all H1-confirmed age 0; no direction conflicts; strategy counts Donchian 22, Keltner 7, MACD 6, EMA 3, RSI 2. These are scanner outputs, not profitability evidence or trade advice.

## 8. Immediate next actions

1. Recheck current main SHA and actual PR #104/#105 states.
2. Recheck research run `44886351505` and hourly scanner run `44886365415`; do not assume they completed.
3. Locate latest workflow artifacts using the available GitHub Actions artifact tools; do not invent artifact IDs or paths.
4. Inspect the latest report's expanded raw session diagnostics:
   - `mapped_raw_candles`, `unassigned_raw_candles`, `raw_candles`
   - `unassigned_reason_counts`
   - `mismatch_reason_counts`
   - `mismatch_field_counts`
   - corporate-action price-basis classifications and examples
   - independent validator status and errors
5. Compare updated diagnostics with the earlier 1,237 / 419 / 5,711 figures; explain what changed and what remains unresolved.
6. If a genuine bug is found, create a focused branch/PR with tests; avoid protected files. Merge only after both mandatory safety checks pass on the exact current PR head.
7. Keep model input on verified native TQBR data unless a separate, documented and independently validated change is approved.
8. Continue improving provenance, lineage, independent audits and prospective evidence. Do not claim statistical significance or profitability until adequate samples exist.

## 9. Communication contract

- User prefers autonomous safe progress and minimal interruptions.
- “Продолжай” means continue without asking the user to repeat known context.
- Report confirmed facts separately from assumptions and next steps.
- Never claim success before tool confirmation.
- Do not claim notifications or background monitoring unless actually configured.
- Do not address the user by name.


## 10. Latest verified research snapshot — run 44886351505

**Generated:** 2026-11-21 08:54:53 UTC  
**Run:** https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/44886351505  
**Source commit:** `691d2a1876460e0f5af5b80dac046e4da6b1d12d`  
**Artifact:** `moex-edge-research-report`, artifact ID `14700094227`, SHA-256 `249fa618027c21178c288a71077fc1bcde057d4529ab6415c839921b6751f021`.

The run completed data collection and analysis for **44/44 tickers with zero history-fetch errors**, but the workflow concluded **failure (exit code 3)** because the report's independent validation status was `INDEPENDENT_VALIDATION_INCOMPLETE`. Do not describe this as a successful/green research run. The report is useful diagnostic evidence, not a validated strategy approval.

### Latest data and reconciliation facts

- Model window: 2023-11-20 through 2026-11-20; 44 symbols; all ticker-level data-quality statuses remain `VALID_WITH_CAVEATS`.
- Holdout begins 2026-11-20. Each ticker has only one prospective holdout daily bar; all five strategy tests per ticker are `INSUFFICIENT_PROSPECTIVE_SAMPLE`, zero closed trades. No statistical conclusions can be drawn.
- Across the raw-session diagnostics: 37,577 raw candles; 37,334 mapped; **243 unassigned**; **1,062 trading days with OHLCV reconciliation mismatches**; 30,387 trading days reconciled; zero TQBR history dates missing raw fragments.
- All 243 unassigned raw candles belong to ticker **T**: 241 are `WEEKDAY_MISSING_SAME_DATE_HISTORY`, 2 are `PRELAUNCH_WEEKEND_UNCONFIRMED`. T has 876 raw fragments, 633 mapped, and 346 mismatched trading dates. Do not map these fragments by guessing.
- The 1,062 mismatch days all classify as `AGGREGATED_OHLCV_DIFFERS`. Largest concentrations: PLZL 342, T 346, VTBR 161, GMKN 94, TRNFP 62. These four/five names overlap known corporate-action price-basis risk; do not auto-adjust. Investigate field-level examples and vendor price basis independently.
- 41 independent-validation warnings, zero validator errors; validator checked 616 items. Status remains `INDEPENDENT_VALIDATION_INCOMPLETE`. It explicitly does not independently establish raw market-data provenance or exchange-wide calendar completeness.
- Native TQBR daily-history OHLCV remains the model input. Raw fragments remain diagnostics only.

### Latest development portfolio diagnostics

These are development-only and not evidence of profitability:

| Position cap | Return | Max drawdown | Closed trades | Profit factor | Slot utilization |
|---:|---:|---:|---:|---:|---:|
| 5 | -18.81% | -40.12% | 955 | 0.946 | 95.48% |
| 7 | -12.19% | -34.86% | 1,277 | 0.964 | 94.04% |
| 10 | -12.09% | -34.72% | 1,673 | 0.964 | 91.33% |

A separate continuous-development replay (positions may cross fold boundaries) was also negative: cap 5 return -26.58%, DD -41.96%; cap 7 return -21.98%, DD -44.58%; cap 10 return -17.82%, DD -37.66%. Do not mix these two portfolio protocols.

The experiment lab completed 132 development-only trials across three exit configurations. It is exploratory and does not modify the frozen cohort. No holdout tuning is allowed.

### Immediate research priorities after this run

1. **T unassigned candles:** inspect the 243 dates and raw ISS response metadata. Establish whether they represent missing TQBR history, ticker listing/trading transitions, or another data-source behavior. Preserve unassigned classification until supported by evidence.
2. **Corporate-action-heavy mismatches:** inspect OHLCV field mismatch distributions and dates for PLZL, T, VTBR, GMKN, TRNFP. Distinguish price-scale differences from volume-only differences. Verify event effective dates, trading resumption dates, and vendor series basis from primary sources. No automatic adjustments.
3. **Ordinary residual mismatches:** inspect examples for the other tickers; do not treat a low count as harmless without classification.
4. Improve the independent validator only when a genuine diagnostic inconsistency is identified; do not weaken fail-closed criteria to make the workflow green.
5. Continue prospective holdout collection without tuning. A single day is insufficient; the minimum sample remains 30 closed trades per hypothesis plus the frozen statistical controls.
6. The hourly workflow run 44886365415 completed successfully in the same snapshot; this is scanner operation only, not a validation of the daily research results.

### PR #106 handoff document publication

PR #106 was merged after both mandatory tests passed on exact head SHA `4a13197a7377fe7dc48b0d6f424d80fa01bbddba`:
- Research Agent Safety Tests: run `44887056352`, success.
- Finam Executor Safety Tests: run `44887056184`, success.
- Merge commit: `b89fb7a716cad268fc4c516cf9cbd4366efd641c`.

The Research Agent Safety Tests workflow path filter now includes `docs/HANDOFF.md`, so future edits to this handoff file trigger the research safety tests. This change does not trigger or modify any production workflow.


## 11. TCSG legacy ticker reconciliation and latest corporate-action audit — 2026-11-21

**Current main SHA:** `b314dacf6b62989266347e638f700427b98ff505`

### PR #108 — legacy TCSG alias for raw reconciliation only

PR #108 was merged at 2026-11-21 09:02:08 UTC:
- PR: https://github.com/vkazarin763-cloud/moex-edge-fast1/pull/108
- PR head: `2e308ec7c0b3a0ee4528783907615ee2c47e4c43`
- Merge commit: `b314dacf6b62989266347e638f700427b98ff505`
- Research Agent Safety Tests: run `44887595233`, success on the exact PR head.
- Finam Executor Safety Tests: run `44887595203`, success on the exact PR head.

The change fetches official TCSG TQBR history through 2024-11-27 because MOEX changed the ticker to T effective 2024-11-28 (source: https://www.moex.com/n74886). TCSG rows are used only for raw-candle/session reconciliation and raw-history cross-checks. They are not added to the current T research/model input. Current T model input continues to use only T TQBR history. The regression test is `tests/test_research_legacy_ticker_reconciliation.py`.

The PR evidence records 243 pre-rename T daily-candle dates and 243 positive-trade TCSG history dates over 2023-11-20—2024-11-27, including two working Saturdays confirmed by same-date positive-trade history. After the alias fix, no raw T candles remain unassigned in the focused corporate-action audit.

### Focused corporate-action audit after PR #108

- Workflow: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/44887641981
- Completed: success.
- Source commit: `b314dacf6b62989266347e638f700427b98ff505`
- Artifact: `moex-corporate-action-price-basis-audit`, ID `14701230075`.
- Data through 2026-11-20; scope GMKN, TRNFP, VTBR, PLZL, T.
- The workflow succeeded in collecting and producing the report, but the report's independent validator remained `INDEPENDENT_VALIDATION_INCOMPLETE` (70 checks, 5 warnings, 0 errors). The five warnings are the remaining raw-session reconciliation mismatches; do not call this a clean data-quality pass.

| Ticker | Model bars | Raw bars mapped | Unassigned | Trading-day mismatches | Known price-scale matches |
|---|---:|---:|---:|---:|---:|
| T | 499 | 876/876 | 0 | 589 | 588 at factor 10 |
| GMKN | 761 | 899/899 | 0 | 94 | 92 at factor 100 |
| TRNFP | 761 | 899/899 | 0 | 62 | 61 at factor 100 |
| VTBR | 761 | 899/899 | 0 | 161 | 160 at factor 0.0002 |
| PLZL | 762 | 896/896 | 0 | 342 | 341 at factor 10 |

For all five securities, every detected OHLC price-scale mismatch matched the documented pre-event basis; unexplained price-scale mismatch count was zero. This is a diagnostic ratio match, not proof that all vendor OHLCV history is correct. Volume was not adjusted. No automatic price or volume adjustment was made.

T's 499 model bars begin on 2024-11-28. The legacy TCSG observations remain excluded from model input by design; 499 is one bar below the preferred 500-bar history threshold, although above the 200-bar warmup requirement. Keep the caveat visible.

All five focused-audit symbols have zero unassigned raw candles and complete raw date coverage, but retain raw OHLCV mismatches. Their history cross-check remains `CROSSCHECK_INCONCLUSIVE` because raw calendar-date fragments are not a one-to-one set of TQBR trade-date rows.

### Cross-universe residual mismatch dates — unresolved

The previous 44-symbol report (run `44886351505`, source commit `691d2a1876460e0f5af5b80dac046e4da6b1d12d`) shows a striking concentration:
- 2025-04-10 appears as a mismatch date for 36 of 44 symbols.
- 2025-10-27 appears for 19 of 44 symbols.
- The 2025-04-10 examples commonly differ in low/close and volume; the 2025-10-27 examples are often volume-only.

A full targeted hourly check was then completed for all 36 symbols with a 2025-04-10 mismatch in the 44-symbol report:
- All 36 had hourly TQBR candles through 23:00; 35 returned 18 hourly bars, while OZON returned 15.
- Aggregating the hourly bars (first open, maximum high, minimum low, last close, summed volume) matched the stored TQBR history OHLCV for **all 36/36 symbols**.
- Direct interval-24 CSV checks for SBER and GAZP showed the daily candle ending at 19:04:15, while hourly bars continued through 23:59:56/57. For SBER, interval-24 volume was 49,360,530 versus 62,862,840 from hourly aggregation/history; for GAZP, 119,247,830 versus 153,296,370.
- This establishes that the 2025-04-10 mismatch cluster is explained for all 36 tested symbols by the interval-24 daily candle not representing the complete TQBR trading day, while the full hourly aggregation reconciles to history. Keep D1 candles from this endpoint out of the role of full-session reference for this date. Official MOEX schedule lists the evening session 19:00–23:50: https://www.moex.com/ru/stock-market.

A targeted 2025-10-27 check covered all 19 symbols with volume mismatches:
- All 19 returned 18 hourly bars through 23:00. Hourly aggregation reproduced the daily interval-24 candle volume for each symbol.
- OHLC matched TQBR history in the original report, but the TQBR history VOLUME field remained different. For GAZP, interval-24 and hourly volume were 44,070,553 versus 46,407,070 in history, while OHLC matched and the daily candle ended at 23:59:59.
- This is a separate unresolved volume-definition/source-scope discrepancy. Do not normalize or overwrite history volume until the ISS field semantics are independently established.

These patterns suggest a shared session-coverage or data-aggregation issue, but the cause is **not established**. MOEX announced an expansion of morning/evening session eligibility effective 2025-04-11 and a separate morning-session addition for fund AKMP effective 2025-04-10 (https://www.moex.com/n89301). That announcement alone does not explain the broad 36-symbol mismatch pattern. Do not label the residuals as harmless, and do not weaken reconciliation tolerances.

### Next actions

1. Inspect the MOEX ISS daily candle endpoint's session/aggregation semantics against full TQBR history for representative symbols on 2025-04-10 and 2025-10-27.
2. Compare daily candle OHLCV with intraday candle aggregation across all available sessions; explicitly document which sessions are included and whether the daily endpoint is a subset of full history.
3. Recheck other residual mismatch dates after the common dates are understood; distinguish volume-only from price-field differences.
4. Keep official TQBR history as the frozen model-input source. TCSG remains reconciliation-only.
5. Do not change the frozen cohort, holdout, strategies, costs, execution model, or broker/production code.


## 12. User-facing D1/H1 signal pipeline and scheduled automation proposal

### Correct signal artifact vs legacy hourly log

- The legacy workflow run `44887560484` (`MOEX EDGE FAST (Hourly Trading)`) produced 16 SHORT rows, all marked H1-confirmed, but its `moex_signals.csv` contains `entry_price` and `qty`. This conflicts with the current user-facing output contract (signals, direction, strategy, H1 confirmation, indicator parameters only). Do not present that legacy CSV as the compliant signal report. The legacy workflow and protected executor files remain untouched.
- The read-only MTF scanner run `44868142437` produced 40 signals from 44/44 symbols with D1/H1 data and zero skipped symbols. Artifact `moex-edge-mtf-signals-44866432461`, ID `14692458973`. Its signal objects contain symbol, direction, strategy, D1 timestamp/close, indicator parameters, H1 confirmation/alignment and conflict status; no quantity, position size, capital allocation, or entry-price sizing fields.
- The MTF scanner uses the five frozen strategy formulas and applies H1 alignment as informational confirmation only; it does not filter or rank signals. It is read-only and does not call account/order endpoints.

### PR #111 — scheduled lightweight D1/H1 scan

Branch: `feat/scheduled-d1-h1-signal-scan`. Proposed changes:
- Add a `--frames` selector to `research_agent.multi_timeframe`; default behavior remains the full existing timeframe collection. Explicit selection requires D1 and supports the scheduled `D1,H1` collection.
- Schedule the MTF candle workflow for weekdays at 05:00 UTC and trigger it on relevant main-branch code changes. Scheduled/push runs fetch only MOEX TQBR D1 history and Finam H1 candles, avoiding the other ten timeframe feeds.
- Keep manual full-timeframe collection behavior intact.
- Trigger the read-only MTF signal scanner after a successful collection run and publish a concise GitHub Actions step summary with symbol, direction, strategy, D1 close and H1 confirmation.
- Add tests for D1/H1-only collection and explicitly prohibit sizing/capital fields in MTF signal objects.

The scheduled data path is read-only: D1 is native MOEX ISS TQBR history; H1 is Finam market data. It does not submit orders, calculate quantity, allocate capital, or modify the frozen research cohort/holdout. Do not claim it is active until PR #111 is merged and the first push-triggered run is confirmed successful.


## 13. Accelerated D1/H1 collection and first automated signal cycle — 2026-11-21

**Current main SHA:** `15fdcbb3396493e9bd45e90efb0e10a7d48e5b86` (PR #112 merged).

### PR #112 — reduce latest-signal D1 history

- PR: https://github.com/vkazarin763-cloud/moex-edge-fast1/pull/112
- Change: `research_agent/multi_timeframe.py` latest-signal D1 TQBR-history lookback reduced from five years to 365 calendar days.
- Frozen research dataset, frozen cohort, holdout, strategy formulas, and execution configuration are unchanged.
- Regression test added in `tests/test_research_multi_timeframe.py` for the bounded D1 date range.
- Both required safety workflows passed on exact PR head `5478c3c3a161e0371574fc062a5726d1746869c1`: Research Agent Safety Tests and Finam Executor Safety Tests.
- PR merged; main is `15fdcbb3396493e9bd45e90efb0e10a7d48e5b86`.

### Actual collection runtime comparison

- Previous five-year collection run: [44888476975](https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/44888476975), 09:12:33–09:23:28 UTC = 655 seconds.
- Optimized one-year collection run: [44889538524](https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/44889538524), 09:25:44–09:29:39 UTC = 235 seconds.
- Measured end-to-end workflow duration decreased by 64.1% (655s to 235s). This is one before/after pair, not a long-run performance guarantee.
- The optimized collection run and its validation both concluded success.

### Downloaded artifact and independent structural checks

Collection artifact: `moex-edge-multi-timeframe-candles`, ID `14701243872`; validation artifact file is `moex_edge_multi_timeframe_validation.json`.

- Validation status `PASS`, 44 symbols, `issue_count=0`.
- D1: 44/44 OK, 11,128 completed bars total, 249–253 per symbol; dates 2025-11-21 through 2026-11-20.
- H1: 44/44 OK, 18,648 completed bars total, 421–424 per symbol; observed candle timestamps 2026-10-22 through 2026-11-21.
- Independent artifact inspection found zero missing symbol/frame series, zero duplicate timestamps per symbol/frame, zero unsorted series, and zero invalid OHLC rows across D1 and H1.
- D1 source remains MOEX ISS native TQBR history; H1 source remains Finam. No resampling, interpolation, or provider merging. Only completed bars are included.
- The reduced D1 window is for the latest-signal collector only; it must not replace the longer frozen research dataset.

### First automated signal scan on optimized data

- Downstream scanner run: [44889832277](https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/44889832277), success.
- Artifact: `moex-edge-mtf-signals-44889538524`, ID `14701034488`.
- `generated_at_utc=2026-11-21T09:29:54.845134+00:00`; `as_of_utc=2026-11-21T09:25:51.184499+00:00`.
- Universe 44; D1/H1 data 44/44; signals 40; skipped 0.
- Direction: 40 SHORT, 0 LONG. This is a point-in-time output, not an instruction to trade short.
- Strategy counts: Donchian20 22; Keltner20x2ATR 7; MACD12x26 6; EMA20x50 3; RSI14Trend50 2.
- H1 status: all 40 `CONFIRMED`. H1 remains informational confirmation and does not suppress D1 signals.
- Recursive output-key audit found none of: `qty`, `quantity`, `position_size`, `capital`, `allocation`, `investment_amount`.
- The output is a read-only prototype signal report. It is not evidence of profitability or statistical edge. No prospective outcome sample has accrued sufficient trades; do not tune on the holdout.

### Current project status and next actions

1. The scheduled weekday D1/H1 collection and downstream read-only signal scan are operational on main. The configured schedule is 05:00 UTC weekdays; do not claim background monitoring beyond the actual GitHub Actions schedule/runs.
2. Continue verifying scheduled runs and artifacts: coverage, validation, closed-bar timestamps, scanner success, skipped symbols, signal composition, and absence of sizing/capital fields.
3. Preserve the frozen cohort `v1-frozen-2026-11-19`, 2026-11-20 prospective holdout start, 44-symbol universe, five strategies, statistical controls, costs, and execution model. Do not tune based on holdout results.
4. Build/maintain a prospective signal-outcome ledger only as a separate, auditable component; do not alter the frozen scanner rules or claim edge before adequate sample and valid statistical tests.
5. The legacy hourly workflow still has a separate CSV output containing `entry_price` and `qty`; do not present that legacy CSV as the compliant signal-only report. Do not modify its workflow or protected executor files as part of this MTF work.
6. Keep the research agent read-only. Never call broker order endpoints, enable live trading, or expose credentials. Do not use `workflow_dispatch` for project runs.

## 14. Prospective signal ledger and frozen execution replay — 2026-11-21

**Verified main commit:** `0720be08b53c3f0bf75f7d343e1aa8de941ce1a0` (PR #122 merge commit). This supersedes the older main-SHA snapshots above; those historical snapshots are retained as dated context, not current state.

### PR #114–#118: signal and execution evidence pipeline

- **PR #114** added the append-only signal ledger core: deterministic event identity, JSONL append, idempotent duplicate handling, and fail-closed behavior for malformed or materially changed records.
- **PR #115** added the isolated ledger workflow. It consumes only a successful main-branch scanner artifact and writes to the dedicated `moex-edge-signal-ledger` branch; it does not write to main or use broker credentials.
- **PR #116–#118** added historical signal replay and frozen-cost execution replay as separate artifacts. Historical replay uses the frozen core signal generator and strict pre-holdout cutoff; execution replay uses the frozen backtest engine/configuration.
- Frozen protocol and holdout remain unchanged. Historical replay is development evidence only; prospective evidence starts at 2026-11-20.

### PR #122: ledger floating-point idempotency correction

- PR: https://github.com/vkazarin763-cloud/moex-edge-fast1/pull/122
- Merged: 2026-11-21 10:24:23 UTC.
- Head SHA: `690b40c4d8cd0f2fc8ea741838408c56c72771ee`.
- Merge commit: `0720be08b53c3f0bf75f7d343e1aa8de941ce1a0`.
- Required checks passed on the exact PR head: Research Agent Safety Tests run `44894114142`; Finam Executor Safety Tests run `44894114148`.
- Numeric repeat-event comparison now uses `math.isclose(rel_tol=1e-9, abs_tol=1e-8)`; booleans remain type-strict and structural changes remain strict. The regression test covers the observed approximately 1.08e-6 drift in YDEX H1 EMA50 around 3346. First-observed payloads are preserved unchanged.
- Ledger workflow run `44893403407`, attempt 4, completed successfully after the fix. It appended/confirmed 40 records with 40 unique event IDs, all in cohort `v1-frozen-2026-11-19`; 40 SHORT, 0 LONG, 27 distinct symbols; D1 bar end `2026-11-20T21:00:00+00:00`. Ledger file SHA at verification: `375af14d6d72eb5b3b8d2d7bfb9879a9cc243749`.

### Latest automated signal cycle known at this snapshot

- Collector run `44893026379`: successful; 44 D1/H1 series; independent validation reported no known issues.
- Scanner run `44893384222`: successful; 44 symbols checked; 40 signals, all SHORT; all 40 H1-confirmed. Strategy counts: Donchian20 22, Keltner20x2ATR 7, MACD12x26 6, EMA20x50 3, RSI14Trend50 2.
- Historical replay run `44893384340`: successful.
- These are operational scan/replay outputs, not evidence of profitability. The 40 signals are a point-in-time observation, not a trading instruction.

### Historical execution replay — interpretation guardrails

The frozen execution replay is separate from the prospective ledger. Its configuration remains stop 3%, target 6%, max hold 120 D1 bars, commission 0.1% per side and slippage 0.05% per side. It uses next-open entry and the frozen stop/target gap rules. Historical observations overlap across symbols/strategies and are not a portfolio simulation or statistically validated edge. Do not use the replay to tune the prospective holdout.

### Immediate next actions

1. Keep the weekday D1/H1 collector, read-only scanner, and isolated ledger running on their existing schedules/triggers; inspect actual Actions results when available rather than claiming background monitoring.
2. Confirm the next successful collector → scanner → ledger cycle and check that duplicate events remain idempotent.
3. Accumulate prospective outcomes without changing the frozen cohort, formulas, exits, costs, or holdout.
4. Do not tune until each tested hypothesis has at least 30 closed prospective trades and all frozen statistical controls can be applied.
5. Keep all broker execution paths out of this research workflow. Never use `workflow_dispatch`, live orders, or credentials.

