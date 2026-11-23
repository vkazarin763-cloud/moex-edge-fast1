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
- Latest CI workflow run observed at handoff preparation: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45109696114 (in progress on SHA `2289d57...`). Another intermediate run `45109691481` was also in progress. Check the latest run and do not assume it passed until completed.

## Next actions (continue autonomously in this order)
1. Verify run `45109696114` and the newest branch CI. Confirm compile plus both `tests.test_research_ai_team` and `tests.test_research_holdout` pass. Fix failures on this feature branch only.
2. Inspect the exact raw-candle/TQBR reconciliation mismatch dates and session mapping for SBER, GAZP and MOEX. Trace source rows, board/session timestamps and aggregation logic. Do not label them harmless without evidence.
3. Investigate the 9 calendar-gap candidates per ticker against an authoritative MOEX trading calendar. Do not assume weekends/holidays explain every gap; distinguish expected non-trading days from missing data.
4. Add focused tests and improve the report's calendar/reconciliation diagnostics. Keep `INDEPENDENT_VALIDATION_INCOMPLETE` until the warnings are genuinely resolved.
5. Rerun the real-data workflow only after fixes; verify artifacts and all 50 registry rows again.
6. Keep PR #163 open/unmerged. Do not touch production repository, broker integration, live trading, Telegram, or paid services.

## User working preferences
- Work in practical increments; minimize requests for manual user steps.
- Explain results in plain Russian.
- User expects independent verification and honest limitations.
- The goal is to prove whether the free agent workflow is useful before paying for faster models.
