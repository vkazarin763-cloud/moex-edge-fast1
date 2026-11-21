# MOEX EDGE — project handoff

**Snapshot date:** 2026-11-21  
**Repository:** https://github.com/vkazarin763-cloud/moex-edge-fast1  
**Default branch at snapshot:** `main`  
**Main SHA at snapshot:** `691d2a1876460e0f5af5b80dac046e4da6b1d12d`

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
