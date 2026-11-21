# MOEX EDGE — handoff for another AI
Updated: 2026-11-17 (UTC)
Repository: https://github.com/vkazarin763-cloud/moex-edge-fast1
Default branch: main

## Critical safety state
- The repository contains a real-money Finam Executor. Do not assume a test run is harmless.
- No live order was sent by this work session. No broker API credentials or Telegram secrets were read, printed, or changed.
- Do not switch live trading on, merge this PR, or dispatch the executor until the owner has reviewed broker API request/response schemas, idempotency semantics, fill reconciliation, protective-order behavior, and Actions configuration.
- The user explicitly authorized live trading, but that is not evidence that the implementation is ready.
- `FINAM_DRY_RUN` is passed to the two executor workflows via GitHub Actions Variable `vars.FINAM_DRY_RUN`, with fail-safe default `true`. Missing variable means DRY_RUN. Live mode would require the repository owner to set Actions Variable `FINAM_DRY_RUN=false` after independent review. This has NOT been set by this work.
- The workflow environment wiring is in a Draft PR only; main remains unchanged.
- Tests are mocked/unit tests, not broker integration tests.

## Current executor hardening PR
- Draft PR #5: https://github.com/vkazarin763-cloud/moex-edge-fast1/pull/5
- Branch: `fix/finam-executor-hardening-20261117`
- Last verified head SHA: `8a55c10237361cc55e0761d8541a9fb5bf18eaa5`
- PR state at last check: open, draft=true, merged=false, mergeable=true.
- CI run: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/44140128196
- Result: success. Python compilation passed; 10/10 isolated Finam executor unit tests passed.
- The test suite uses mocks; it does not prove Finam API integration or live execution safety.

## Changes in PR #5
- Executor hardening based on the earlier fill-protection branch: client_order_id, reconciliation after ambiguous submission, polling terminal order state, VWAP from actual trades, protective SL/TP only for confirmed filled quantity.
- Added reconciliation for ambiguous HTTP 5xx/408 responses by client_order_id; never blindly retry a potentially accepted order.
- Cancellation response timeout is reconciled by re-reading order state.
- Explicit parsing of FINAM_DRY_RUN: true/false values accepted; invalid value raises and fails closed.
- Both `.github/workflows/moex-edge-fast.yml` and `.github/workflows/finam-executor.yml` pass `FINAM_DRY_RUN` from Actions Variables with default `true`.
- Added mocked tests and isolated safety CI workflow.
- Added journal updates and this handoff.
- Do not assume the PR was merged: it is still Draft/open.

## Required next checks before any live trading
1. Review the entire PR #5 diff and ensure the executor implementation is correct against the currently documented Finam API.
2. Verify Finam API semantics for client_order_id uniqueness, order lookup, status transitions, cancellation races, trades/fills endpoint, stop-loss/take-profit order types, quantity units, and price precision.
3. Verify partial-fill and late-fill behavior: protective orders must cover only actual filled quantity and must be amended if additional fills occur.
4. Verify behavior if SL succeeds and TP fails, or vice versa; ensure orphaned exposure is detected, logged, alerted, and handled safely.
5. Verify no duplicate protective orders and no duplicate market orders across retries/restarts.
6. Review GitHub Actions secrets and Variables in the repository UI. Never ask the user to paste credentials into chat. Confirm required secret names and account permissions without exposing values.
7. Confirm intended account/environment, instrument mapping, lot sizes, trading session handling, rate limits, and maximum order constraints.
8. Add broker sandbox/integration tests if Finam offers a sandbox. Do not use the real account as a test harness.
9. Only after review and explicit owner decision, merge the PR and configure live mode. Keep DRY_RUN default true in code/workflows.
10. First live activation, if eventually approved, should be a separately controlled operator action with immediate monitoring and a documented rollback path. Do not automate an unattended live dispatch based solely on this handoff.

## Other project workstreams — keep separate
- Signal Bot PR #3: Draft branch `feature/moex-edge-signal-bot-20261117`. Read-only Telegram signal notifications; not Finam execution. It passed its previously recorded 5/5 unit tests. User confirmed Telegram messages arrive and schedule works, but that is not evidence of Finam Executor Telegram delivery.
- Finam Telegram wiring PR #4 was merged to main (merge commit `ab95391d8b177d348ce8b1ff8e838e396d304ada`). It maps TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID into both executor workflows. This does not confirm secret existence or message delivery.
- Earlier broad executor PR #1: Draft/open and not merged; do not assume its changes are in main. PR #5 is a separate branch based on main.
- AI Virtual Agent fix was merged in main previously. Do not run agent/trainer manually if it mutates virtual portfolio or model weights; preserve the user's one-month experiment.
- Do not change scanner strategy, Signal Bot rules, AI weights, virtual portfolio, or schedules unless explicitly asked.
- `.github/workflows/futures-scan.yml` was previously found malformed (Python content where YAML is expected) and its Actions runs showed zero jobs/failure. Treat as a separate issue; do not mix into this executor PR.

## User preferences and project constraints
- User prefers the assistant to do practical work with minimal technical questions and explain outcomes in plain Russian.
- Do not invent prices, signals, backtest metrics, execution status, or API test results.
- Clearly distinguish user-reported behavior from independently verified evidence.
- Preserve journal trail in PROJECT_CONTEXT.md, DECISIONS.md, and CHANGELOG.md.
- Avoid exposing secrets or account identifiers in logs, PR descriptions, or handoff files.


## 2026-11-17 — follow-up Finam API audit and hardening
- Latest branch commit after follow-up code/test changes: `c30cdd9ae5c1b99f6a0bd5130c1cd7d9f9aa9555`.
- Latest verified successful CI remains run `44140543355` on the earlier commit `6e30a80733f8bfa463aac62974946ab1ed4a3cda` (compile + 10/10 tests). The GitHub connector did not return a PR-triggered run for the newer commits; do NOT claim the latest code has passed CI yet.
- Reviewed official Finam REST documentation and public protobuf definitions:
  - `client_order_id` is supported and limited to 20 characters.
  - GetOrders returns order states with nested order data; GetOrder, CancelOrder, Trades and PlaceSLTPOrder paths used by the executor exist.
  - AccountTrade exposes `order_id`, `price`, and `size`; the VWAP field mapping is consistent with the official protobuf.
  - GetAsset exposes `decimals`, `min_step`, and optional price-dependent `price_step`; GetAssetParams exposes `trade_lot_size`.
- Follow-up code change: SL/TP is no longer treated as confirmed from HTTP 200 alone. Executor now requires an order_id, returned sltp_order, non-rejected status, and matching echoed SL/TP quantities/prices; otherwise it raises OrderProtectionError and triggers the existing critical Telegram alert/halts later signals.
- Follow-up code change: SL/TP prices are rounded using Finam GetAsset tick metadata, not a hard-coded 2 decimal places. For LONG, SL rounds down and TP up; for SHORT, SL rounds up and TP down. Missing/invalid tick metadata fails closed.
- Added tests for SL/TP response validation and fixed/price-dependent tick rounding. These newer tests have not yet been verified by a completed CI run.
- Remaining live blockers:
  1. Confirm latest CI passes on commit `c30cdd9...`.
  2. Verify repository Actions secrets exist with exact names `FINAM_API_SECRET`, `FINAM_ACCOUNT_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`; do not reveal values. This connector cannot inspect secret values/settings.
  3. Verify Actions Variable `FINAM_DRY_RUN` is currently unset/true; it has not been set false by this work.
  4. Confirm account and permissions, including long/short availability for the instruments, using owner-approved read-only broker checks. No broker credentials were available to this audit.
  5. Resolve remaining operational edge cases: SLTP order read-back / status lifecycle, orphan exposure if protection is rejected, partial/late fills after cancellation, duplicate handling across workflow retries/restarts, and price precision with live instrument examples.
  6. Confirm exact Finam account-specific behavior in sandbox or other non-live environment if available. Do not use real account as a test harness.
- PR #5 remains Draft/open, not merged. Do not merge or enable live trading until the above items are completed and latest CI is green.
- At the time of the initial hardening note, no broker API calls were made. A later read-only Finam audit is documented below; it used only authentication and GET endpoints, never order endpoints. No live orders were sent and no secret values or Actions variables were changed.

- CI follow-up completed successfully after the code, tests, and journal updates: run `44141464912`, job `unit-tests`, compile step passed, `Ran 14 tests`, `OK`. This run corresponds to commit `a19e63308cef5dec7345abcc87abd73e87380663`.

## 2026-11-17 — configuration audit and direction permissions
- Latest executor code/test commit: `6011ff6dd116182af016c7f793c7323a3ac8f338`.
- Latest CI run: `44141866777`, completed successfully. Python compile passed; `Ran 16 tests`; `OK`.
- The isolated safety workflow now checks only presence of runtime configuration and never prints secret values. On run `44141866777` it reported:
  - `FINAM_API_SECRET=present`
  - `FINAM_ACCOUNT_ID=present`
  - `TELEGRAM_BOT_TOKEN=present`
  - `TELEGRAM_CHAT_ID=present`
  - `FINAM_DRY_RUN=safe` (effective safe mode; absent variable defaults to true, explicit live=false was not observed)
- Added account-direction permission validation before an order: LONG requires Finam `longable=AVAILABLE`; SHORT requires `shortable=AVAILABLE` or `AVAILABLE_STRATEGY`; HTB/unavailable statuses are rejected. Added two tests.
- The configuration audit is a GitHub Actions environment check only. It did NOT authenticate to Finam, read account positions, or send broker requests.
- PR #5 remains Draft/open/unmerged; main remains unchanged. Do not set FINAM_DRY_RUN=false yet.
- Still outstanding: non-live broker integration/read-only account verification; exact live account identity and permissions; read-back/status lifecycle for SL/TP; late/partial-fill and cancellation races; orphan exposure handling; final review of all executor paths. The GitHub connector cannot read/modify repository secrets or variables directly; the presence-only workflow check is the available evidence.

## 2026-11-17 — read-only Finam integration and position cap
- Latest executor code/test commit: `4b0587507eb786b569a21c0e9db76f9303e1eeb0`.
- Latest executor safety CI: run `44143462329`, success; compile passed; `Ran 19 tests`; `OK`.
- Configuration check in the same CI confirmed all four secrets present (values not printed) and effective `FINAM_DRY_RUN=safe`.
- Read-only Finam API integration audit succeeded:
  - Run `44143080070`: authentication OK; account GET OK; 44/44 instrument params with valid trade lot; 44/44 tick metadata valid; 44/44 LONG available; 44/44 SHORT available; 0 non-tradable; 0 errors.
  - An earlier successful pass reported 43/44 SHORT available, so availability may vary. Executor now checks account-specific permissions immediately before each order and blocks unavailable/HTB statuses.
  - Audit only used POST /v1/sessions for authentication and GET account/assets endpoints. No orders endpoint was called, and no broker order was sent.
- Added `MAX_OPEN_POSITIONS = 10` and a live-loop guard based on symbols in Finam account positions (which may include theoretical exposure from active orders). New symbols are skipped once the account reaches 10. Added two unit tests.
- `TEST_MODE_MIN_VOLUME = True` remains enabled: any eventual live entry is limited to one minimum trading lot for that instrument. Do not change without explicit user instruction.
- Latest PR head at time of this note may advance with journal-only commits; PR #5 remains Draft/open/unmerged and main remains unchanged.
- Remaining blockers before live: review SL/TP order lifecycle and failure/orphan exposure behavior against Finam's actual account-specific implementation; confirm no open position is left unprotected; ensure operator-approved controlled activation procedure. No live order has been used as a test.
- Effective FINAM_DRY_RUN is still safe; do not set false until the remaining review is complete.

- After successful account/instrument validation (run `44143080070`), the read-only audit workflow was changed to `workflow_dispatch` only. This prevents repeated automatic 90-request audits on every PR metadata/journal update and avoids unnecessary Finam rate-limit pressure. Re-run manually only when a fresh read-only check is needed.

## 2026-11-17 — final SL/TP and fill-reconciliation hardening
- Latest executor code/test commit: `1b40331abc36bcbe05a94df953c6124fd00604e7`.
- Latest CI run: `44144452367`, success; Python compile passed; `Ran 24 tests`; `OK`. Runtime secrets presence and `FINAM_DRY_RUN=safe` also reconfirmed.
- Trade-history reconciliation now polls up to 10 times for the exact executed quantity, allowing Finam history propagation delay. If it remains mismatched or exceeds the order's executed quantity, it fails closed and alerts; SL/TP is not placed on an unverified quantity.
- SL/TP placement now requires both POST response validation and GET read-back through GetOrder. It checks an active status, no triggered child order, matching order id, symbol, exit side, quantities, and prices. Triggered, rejected, unknown, or mismatched states stop the run and send a critical alert.
- Account free cash, open symbols, and occupied sectors are no longer printed in workflow logs; only counts/statuses are logged.
- MAX_OPEN_POSITIONS=10 and TEST_MODE_MIN_VOLUME=True remain active.
- Read-only Finam audit run `44143080070` verified account access and 44/44 lot/tick metadata; latest pass 44/44 LONG and 44/44 SHORT. It used only authentication and GET endpoints, no order endpoints.
- These controls are unit-tested/mocked plus read-only account API validated. No live order or SL/TP order was submitted; actual SL/TP lifecycle on a live or sandbox order remains unverified.
- PR #5 remains Draft/open/unmerged. Main remains unchanged. Effective FINAM_DRY_RUN remains safe; do not set false until final owner-approved activation review.

## 2026-11-17 — active-order position cap follow-up
- Added `get_active_order_symbols()`: read-only GET of account orders; active and unknown-status orders reserve a ticker slot. Terminal orders do not reserve a slot. Malformed/unavailable order list fails closed and prevents new submissions.
- Open position symbols and active order symbols are combined before applying `MAX_OPEN_POSITIONS=10`. This fixes the earlier gap where only positions were counted.
- Added tests for active order reservation, unknown statuses, and malformed order-list response.
- Latest safety CI for commit `011d9a98a4f25b12bef5e179ac88d01471d4f2e8`: run `44156645285`, compile passed, 27/27 tests passed. Runtime secrets present; effective `FINAM_DRY_RUN=safe`.
- Official Finam REST docs confirm GetOrders and GetOrder endpoints and that client_order_id is a unique identifier up to 20 chars; docs do NOT establish client_order_id as an idempotency guarantee. Implementation uses it for reconciliation only and never blindly retries POST.
- PR #5 remains Draft/open/unmerged. No real orders sent. Live mode remains disabled.
- Remaining live blockers: controlled broker sandbox test of market-order → partial-fill/cancel → trades reconciliation → SL/TP creation and GetOrder read-back; verify real SL/TP active lifecycle, failure/orphan exposure handling, tick-price rounding semantics and account-specific behavior. A read-only account audit is not a substitute for these checks.

 
## 2026-11-17 — latest follow-up audit
- Current PR #5 head: `bf7ed4f110f1a25551cef1d471ef5ade08d8ee0a`.
- Safety CI run `44157773263`: success; compile passed; 30/30 tests passed. The workflow confirmed all four required secrets are present (values masked) and `FINAM_DRY_RUN=true`.
- SL/TP POST now uses its own 20-character client_order_id, explicitly sets `SLTP_QTY_MEASURE_VALUE` for both legs, and reconciles ambiguous timeout/5xx/408 responses via GetOrders then GetOrder. It never blindly repeats SL/TP POST.
- GetOrders entries with missing symbols fail closed. Unexpected exceptions after market-order submission are caught by the critical alert/stop path.
- Finam docs: `SLTP_QTY_MEASURE_VALUE` is shares and `SLTP_QTY_MEASURE_PERCENT` is percentage of position; price-dependent tick uses `step` below threshold and `step_from_threshold` at/above threshold.
- Important newly confirmed blocker: the active scanner writes `moex_signals.csv` rows with `ticker,direction,strategy,h1_confirmed,date,entry_price,qty`; executor filters only H1-confirmed and positive qty and does not persist processed signal IDs. If a position closes while the same signal remains active, a later hourly run may enter again. Add and test durable signal idempotency before live.
- Other blockers remain: demo account integration test for the entire order/fill/cancel/SLTP lifecycle; robust recovery/handling if protective SL/TP cannot be confirmed (current behavior alerts and halts later signals but does not automatically close the unprotected position); validate real account-specific SL/TP lifecycle.
- PR #5 remains Draft/open/unmerged. Do not set `FINAM_DRY_RUN=false`, do not merge to main, and do not dispatch live executor until blockers are resolved. No live orders were sent.

 
## PR head after journal update
- Journal-only follow-up commits advanced PR #5 to `531c9fe0e151be95e40a464a780f8653d04f421c`.
- The executor code and tests validated by run `44157773263` are unchanged from code commit `bf7ed4f110f1a25551cef1d471ef5ade08d8ee0a`; the later commits only update project journals and PR documentation.

## 2026-11-17 — durable signal deduplication follow-up (latest changes)
- The executor branch contains stable signal fingerprinting based on `ticker,direction,strategy,date,entry_price` and a durable `finam_signal_state.json` journal stored through GitHub Contents API.
- In live mode, journal reads/writes fail closed. The signal is reserved as `SUBMISSION_ATTEMPTED` before the broker market-order POST. Existing reservations block re-entry even after a position closes. Ambiguous outcomes are not retried automatically.
- The active scanner's `.github/workflows/moex-edge-fast.yml` was corrected to grant `contents: write`, share concurrency group `finam-executor-account`, and pass `github.token`, repository and ref to the executor. The manual executor workflow now also uses `github.token` (it already shared the concurrency group and contents-write permission).
- Terminal zero-fill outcomes are now journaled as `NO_FILL_TERMINAL`; the same signal remains consumed to avoid retrying a stale CSV signal. Per-row signal_id is reset before processing.
- These changes are in PR #5 branch only. The latest commits still require CI confirmation. No workflow was dispatched and no broker order was sent.
- Important remaining concerns: (1) test durable journal behavior against GitHub Contents API in an isolated non-trading test; (2) confirm no other workflow invokes Finam Executor outside the shared concurrency group; (3) resolve orphan exposure if SL/TP cannot be confirmed; (4) complete a full broker integration test in a non-live environment. The user has stated that a demo account is unavailable; do not use the real account as a test harness.
- `FINAM_DRY_RUN=true`; do not merge/activate live execution based solely on unit tests.

## 2026-11-17 — CI syntax regression and correction
- CI run `44160110042` exposed a SyntaxError in `tests/test_finam_executor.py`: three line continuations contained two literal backslashes. Python compilation of production modules passed, but test discovery failed while importing the test module.
- Corrected the three continuations and added mocked tests for reading and writing the GitHub Contents API signal journal, including SHA-based updates and branch selection.
- Latest observed safety CI run: `44160419914`; dependency install and configuration-presence check passed, Python compile passed, unit tests were still running at last inspection. Do not report the latest suite as green until the run completes.
- Initialized `finam_signal_state.json` as an empty object on the PR branch.
- No real broker order or executor workflow dispatch was performed. Effective `FINAM_DRY_RUN=true`.

## 2026-11-17 — latest verified safety CI after signal journal fixes
- Safety CI run `44160419914` completed successfully on PR merge commit `78f3a81`, which includes branch commit `682493b470758e26e4eb63355770d7633dfe0be0`.
- Python compilation passed; `37 tests` ran and all passed (`OK`). This includes the mocked GitHub Contents API journal read/write tests.
- Configuration check confirmed `FINAM_API_SECRET`, `FINAM_ACCOUNT_ID`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` are present (values masked); effective `FINAM_DRY_RUN=true`.
- Later commits after this run only update journals/handoff documentation; the executor code and test file tested by this run are unchanged.
- CI run details: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/44160419914

## 2026-11-17 — cross-project status reconciliation
- PR #6 `Restore valid MOEX futures scan workflow` was merged to main (merge commit `2337fda89ec7ab875444feaa240c67b2747121e1`). The formerly malformed `.github/workflows/futures-scan.yml` is now valid YAML and runs the read-only `futures_scanner.py` on manual dispatch and hourly weekdays. A validation workflow checks YAML structure and Python compilation; run `44161381744` succeeded. This scanner does not place broker orders.
- PR #1 (older Finam fill/SLTP hardening draft) was closed as superseded by PR #5; do not reopen/merge it.
- PR #2 (AI Virtual Agent Kelly scope fix) remains Draft/open. Its CI run `44130237213` passed 3/3 tests and compile checks; branch is not mergeable against the current main revision, so it was not merged. The current main `ai_agent.py` already contains a module-level `get_kelly_pct`; no AI Trainer, weights, or virtual portfolio were changed in this follow-up.
- PR #3 Signal Bot remains Draft/open. CI run `44136770256` passed 5/5 tests and compile checks. User has reported that Telegram messages arrive and the schedule works; this is user-reported runtime evidence, not independently verified in this session. Do not merge/enable another scheduled notifier without checking for duplicate messages.
- PR #5 remains Draft/open/unmerged. Its tested executor revision passed run `44160419914`: compile passed and 37/37 tests passed. Subsequent changes were documentation-only. PR #5 now needs reconciliation with the latest main commit (PR #6 merge) before merge; GitHub currently reports mergeable=false. Do not force-merge.
- Main has changed only through the independent read-only futures workflow PR #6 in this session. Finam executor hardening remains only in PR #5; `FINAM_DRY_RUN=true`; no real broker order was sent.

## 2026-11-17 — actual GitHub Contents API validation and branch fix
- Integration workflow on test PR #7 initially failed because `GITHUB_REF_NAME` is a reserved runner variable. In pull_request context it remains `7/merge` even when an `env:` mapping tries to override it. GitHub Contents API returned 404 for branch `7/merge`.
- Correct design: executor reads `FINAM_STATE_BRANCH` first, with fallback to built-in `GITHUB_REF_NAME`. Production scanner+executor and manual executor workflows pass `FINAM_STATE_BRANCH: ${{ github.ref_name }}`.
- After this correction, real Actions-token integration run `44162894813` succeeded: Contents permission was write; journal reserve/read/update/read all passed on `test/finam-journal-validation`. No Finam credentials, broker endpoints, or Telegram were used.
- Production fix is in branch `fix/finam-executor-journal-env-20261117`, PR pending; run its 38+ test suite before merge. The previous 37/37 CI result predates this branch-env change.
- PR #7 is validation-only; do not merge it. Its test state is isolated to its branch.

## 2026-11-17 — final verified state after PR #8
- PR #5 Finam Executor hardening merged to main (merge commit `2e9379f7658958916c683bb507c9c8fe8ecc06f2`). It includes durable signal deduplication, reservation before order submission, fail-closed journal behavior, terminal zero-fill state recording, active-order position cap 10, fill reconciliation, SL/TP read-back, and shared workflow concurrency. Safety CI on the tested code revision: run `44160419914`, compile passed, 37/37 tests passed.
- PR #8 fixed the reserved Actions environment variable issue by using `FINAM_STATE_BRANCH`; merged to main (merge commit `579306da567aaa2733ffec98a4002306ae66d97b`). Both executor workflows pass the explicit branch. Safety CI run `44163272970`: compile passed, 38/38 tests passed.
- Actual GitHub Contents API integration passed in isolated test branch `test/finam-journal-validation`, run `44162894813`: reserve/read/update/read succeeded using Actions token with Contents:write. No Finam endpoint or broker order was used.
- PR #6 restored the read-only futures scanner workflow and was merged to main (merge commit `2337fda89ec7ab875444feaa240c67b2747121e`); validation run `44161381744` passed YAML structure and scanner compilation.
- PR #1 older executor draft is closed as superseded. PR #7 is validation-only and must not be merged. PR #2 and #3 remain Draft/open; preserve the AI Trainer experiment and avoid enabling a second scheduled Telegram notifier without checking duplication.
- Main workflows keep `FINAM_DRY_RUN` safe by default. Last verified effective value in CI: `true`. No real broker order was sent in this work.
- Live trading remains blocked: no demo-account end-to-end test is available; actual broker partial-fill/cancel/SLTP lifecycle is unverified; safe automatic recovery from unprotected exposure is not implemented. Do not set `FINAM_DRY_RUN=false` or dispatch live execution until these are independently resolved.

## 2026-11-18 — controlled live-test guardrails (PR pending)
- User confirmed no demo account is available and requested validation on the real Finam account. This is implemented as a controlled, manually dispatched mode rather than enabling the hourly schedule.
- Manual executor workflow now offers `DRY_RUN` (default) and `LIVE_ONE_MIN_LOT`. Live mode requires the repository variable `FINAM_DRY_RUN` to be exactly `false`, and first runs the read-only Finam account/instrument audit. Otherwise the job fails before executor start.
- Scheduled scanner+executor workflow is hard-pinned to `FINAM_DRY_RUN=true`, so enabling the manual live-test variable cannot accidentally turn every hourly/weekend schedule into live trading.
- Executor hard limit: at most one new broker-order POST per invocation. Attempt is counted before POST so ambiguous timeout cannot allow a second order in the same run.
- Existing `TEST_MODE_MIN_VOLUME=True` submits exactly one minimum trading lot, not one share. A minimum lot can still have substantial RUB value depending on the instrument; inspect instrument and notional before any live run.
- This is a guardrail, not proof of complete broker lifecycle safety. If SL/TP creation/read-back fails after a fill, current code alerts and halts; it does not automatically close exposure. Owner/operator must be available to inspect the account and intervene. Do not run unattended.
- PR branch `safety/manual-live-one-lot-gate-20261118`; pending CI and review. Until merged and a controlled manual workflow is explicitly selected, no live mode is enabled. Repository variable remains at last verified safe value `true`.

## 2026-11-18 — controlled manual live workflow merged
- PR #9 merged as `83eefa1aa40e340418e7f2672650fce8a2babbca`: explicit manual modes `DRY_RUN` (default) and `LIVE_ONE_MIN_LOT`; read-only Finam audit must pass first; live mode requires repo variable `FINAM_DRY_RUN=false`; scheduled MOEX scanner+executor is hard-pinned to `FINAM_DRY_RUN=true`; executor submits at most one new order POST per invocation. CI run `44225394589`: compile passed, 39/39 tests passed.
- PR #10 merged as `14bb119814e0a53773eb94168c388bec505ab97b`: manual workflow now runs `moex_edge_fast_33.py` to generate a fresh `moex_signals.csv` before calling executor; installs NumPy and uploads scanner output artifact. CI run `44225571966`: compile passed, 39/39 tests passed.
- Existing `TEST_MODE_MIN_VOLUME=True` means one full minimum trading lot (not one share); notional may be material and depends on instrument price and lot size.
- Latest CI confirmed `FINAM_DRY_RUN=safe` (true). No live order has been submitted. The manual live workflow has not been dispatched.
- Remaining live risk: if broker confirms a fill but SL/TP creation/read-back fails, executor alerts and halts; it does not automatically close exposure. Live runs must not be unattended; operator must be able to inspect account and manually intervene. This is not yet a fully self-recovering autonomous live system.
- Before first real run: owner deliberately changes repository variable `FINAM_DRY_RUN` to exact string `false`, then dispatches workflow `Finam Executor — controlled manual run` with mode `LIVE_ONE_MIN_LOT`. Do not change scheduled workflow; it remains pinned to dry-run.


## 2026-11-18 — zero-quantity Finam positions fix and validation
- User checked Finam manually and confirmed there are currently no open positions and no active orders (user-reported UI state; not independently queried from broker API in this session).
- Investigated why executor still logged 1 open instrument in DRY_RUN run `44238708231`. The previous code counted every `account_data["positions"]` record with a symbol, even if Finam's signed `quantity.value` was zero.
- PR #11 merged to main: https://github.com/vkazarin763-cloud/moex-edge-fast1/pull/11 ; squash merge commit `d8d87051d423013b2ca7d1c55cb677334a322760`.
- New helper `get_open_position_symbols(account_data)` counts only non-zero signed quantities. It fails closed on malformed position lists, missing symbols, or missing/invalid quantity. No strategy, signal rules, lot size, live-mode settings, or order submission behavior was changed.
- Added four tests: zero-quantity records ignored; empty positions list; missing quantity rejected; malformed positions response rejected.
- GitHub Actions run `44240882740` completed SUCCESS: Python compilation passed; all 43 unit tests passed. Relevant new tests all passed.
- Main branch file `finam_executor.py` verified to contain the merged helper and use it in `main()`.
- Next mandatory step: manually dispatch `Finam Executor — controlled manual run` in `DRY_RUN` mode only. Check fresh scanner output and confirm executor logs `Открытых позиций: 0/10` (or exact zero count) and no false occupied-symbol skip. Do not dispatch LIVE until this dry-run is reviewed and the actual broker state is independently reconciled.
- Important state distinction: the user previously set repository variable `FINAM_DRY_RUN=false` for a manual live test; one prior run `44234763883` confirmed it was false, but submitted no order because there were no confirmed signals. The scheduled workflow is hard-pinned to dry-run. Do not infer the current repository variable value without a fresh safe check.
- Previous manual run `44238708231` was DRY_RUN, audit succeeded, but executor logged 1 open position; it prepared DOMRF without submitting and skipped T because a position was already counted. That run predates PR #11.
- No new broker order was submitted by PR #11, its CI, or the merge. The next run must remain DRY_RUN.


## 2026-11-18 — controlled live-trial request; latest DRY_RUN checkpoint

- User asked to record the latest result and proceed with a real-mode trial for one day. This is an explicit request for live trading, but it does not mean a live workflow has already been dispatched or that any order has been submitted.
- Latest verified workflow run: `44253089210`, completed SUCCESS on main at commit `60f30705bacfe81fcbc990aa4cc41e8d3027e38a`.
- Read-only Finam preflight passed: authentication/account read OK; valid lot and tick metadata 44/44; LONG/SHORT permissions 44/44; no instrument audit errors; no blocked tickers.
- Fresh scanner signals: DOMRF LONG (Donchian55), H1 confirmed; T LONG (Keltner), H1 confirmed.
- Executor reported 0 open positions out of 10. Environment explicitly had `FINAM_DRY_RUN=true`; both signals were prepared in dry-run only; no broker order endpoint was called and no order was submitted.
- Executor reported `trade_lot_size=1` and prepared quantity 1 share for both DOMRF and T. Scanner printed risk-sized quantities of 1 DOMRF and 11 T. This is a sizing-source mismatch that must remain visible in trial review; do not interpret scanner quantity as the executor's live quantity. Scanner/executor SL/TP for T also differed slightly due to rounding.
- Artifact `manual-moex-signals` uploaded for 7 days: run artifact ID `14404369409`.
- Live-trial guardrails remain: manual workflow choice must be explicitly `LIVE_ONE_MIN_LOT`; read-only audit must pass; at most one new order per workflow run; minimum full exchange lot; maximum 10 open positions; scheduled scanner workflow remains hard-pinned to DRY_RUN. A single manual workflow dispatch is not a continuous all-day service; further executions require separate manual dispatches unless a separately reviewed schedule is configured.
- No live dispatch was performed by the assistant. The current repository variable `FINAM_DRY_RUN` was not re-read in this checkpoint; the successful run above explicitly used true.
- Before each live dispatch, independently verify Finam has no unexpected open positions/orders and confirm the instrument's actual minimum lot and available funds. If any order outcome is ambiguous or protection (SL/TP) is not confirmed, stop further runs and reconcile in Finam manually. Never blindly retry an ambiguous order.


---

# CURRENT AUTHORITATIVE HANDOFF — 2026-11-21 (MOEX EDGE research)

This section is the current project state and supersedes older dated status notes above where they conflict. Older historical notes are retained for audit history; do not assume their PR numbers, branches, trading configuration, or status are current.

## Repository and hard safety boundaries
- Active repository: https://github.com/vkazarin763-cloud/moex-edge-fast1
- Work only in this research repository. Never modify production repository `vkazarin763-cloud/moex-edge-fast`.
- Current main commit at handoff: `a65eeaf3800be1b56deaaa36258a5369fce33cf2` (PR #71 merged).
- Live trading is stopped for this research work. Research agent must remain read-only.
- Never call broker order endpoints, submit/cancel/replace orders, enable live trading, or expose Finam tokens/secrets.
- `FINAM_API_TOKEN` exists as GitHub Actions secret; do not request or print its value.
- Protected files — do not modify for this research project:
  `moex_edge_fast1.py`, `finam_executor.py`, `futures_scanner.py`,
  `futures_executor.py`, `ai_agent.py`, `ai_trainer.py`,
  `ai_portfolio.json`, `ai_weights.json`.
- User authorizes safe PR merges only after both required CI checks pass and the PR head SHA is rechecked.
- GitHub MCP cannot dispatch `workflow_dispatch`; user must manually run Actions workflows when needed.
- User wants autonomous practical progress, Russian explanations, and no fabricated metrics/signals.

## Frozen research design — do not retune
- Prospective holdout starts: `2026-11-20`. Do not use holdout observations to select, rank, optimize, or tune strategies.
- Frozen cohort: `v1-frozen-2026-11-19`.
- Exactly five frozen strategies:
  1. Donchian20 breakout
  2. EMA20x50 cross
  3. RSI14 trend 50 crossing
  4. MACD12x26 crossover
  5. Keltner20x2ATR breakout
- Statistical gates: minimum 30 trades; Newey-West HAC; moving-block bootstrap confidence interval; Holm-Bonferroni correction across family of 220 hypotheses.
- Simulator conventions: signal at close, entry next open; conservative stop-first if stop and target touched same bar; stop gaps execute at open; target gaps execute at target; two-sided commissions/slippage; non-overlapping trades.
- Do not claim profitability without completed valid tests.
- Do not add variants or tune on prospective holdout. Keep development walk-forward separate from prospective holdout.
- Universe frozen at 44 tickers:
  `AFKS,AFLT,ALRS,BSPB,CBOM,CHMF,CNRU,DOMRF,ENPG,FLOT,GAZP,GMKN,HEAD,IRAO,LKOH,MAGN,MDMG,MOEX,MTSS,NLMK,NVTK,OZON,PHOR,PLZL,POSI,RAGR,RENI,ROSN,RTKM,RUAL,SBER,SBERP,SNGS,SNGSP,SVCB,T,TATN,TATNP,TRNFP,UGLD,VKCO,VTBR,X5,YDEX`.

## MTF data collection — current verified artifact
- Workflow: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/44861047844
- Workflow status: completed, `success`; run ID `44861047844`; job `collect` succeeded.
- Run commit: `a65eeaf3800be1b56deaaa36258a5369fce33cf2`.
- Artifact name: `moex-edge-multi-timeframe-candles`; artifact ID `14690518588`; uploaded 2026-11-21; retention 30 days.
- Artifact ZIP filename in working environment: `moex-edge-mtf-44861047844.zip`.
- ZIP SHA-256: `6a9ee767f37bec1f9fa9d40d0868ccc8f36b2271dd5ef4a1715f83e4a51af137`.
- ZIP contains `moex_edge_multi_timeframe_candles.json` and `moex_edge_multi_timeframe_validation.json`.
- JSON snapshot `generated_at_utc/as_of_utc = 2026-11-21T03:25:33.304483+00:00` (06:25:33 Europe/Moscow).
- Validator status `PASS`, 44 symbols, 13 frames, `issue_count=0`.
- Independent local recheck across every candle: 787,929 total bars; zero duplicate timestamps, non-monotonic series, invalid/non-finite OHLCV, OHLC inconsistencies, negative volume, Finam snapshot=true records, or bars whose native interval end is after as_of.
- Frame counts (each frame has 44/44 non-empty symbols):
  - Finam M1 247,364; M5 218,870; M15 74,160; M30 37,256; H1 18,781; H2 10,114; H4 5,500; H8 3,344.
  - MOEX ISS M10 110,962; W1 10,088; MN 2,322; QR 750.
  - MOEX ISS native TQBR D1 history 48,418.
- Exclusions reported by collector: Finam snapshot=true 0; incomplete Finam intraday 0; unknown Finam snapshot flags retained 0; MOEX incomplete W1/MN/QR 44 each (one per symbol); D1 zero-trade rows 826 total; D1 incomplete/invalid rows 0.
- All 44 tickers have a latest closed H1 and D1 bar. D1 data is sourced from native per-security TQBR history, not resampled from intraday. Finam and MOEX feeds remain separate. No resampling, filling, interpolation, or provider merging.
- Time handling: Finam timestamps timezone-aware UTC; naive MOEX timestamps interpreted as Europe/Moscow. Validator uses native timeframe durations and excludes bars ending after as_of.
- Artifact is a workflow artifact with 30-day retention; retrieve it using GitHub Actions artifact ID above. Do not put the 100MB uncompressed JSON into Git history. Preserve ZIP checksum and run ID when handing off.
- Full frame-level counts/exclusion details are in `docs/MULTITIMEFRAME_DATASET_2026-11-21.md`.

## Relevant merged PRs in research repository
- PR #63 — conservative weekend handling; original dates retained; unverified weekend bars diagnostic-only.
- PR #64 — report metadata/docs corrected for weekend handling.
- PR #65 — research eligibility filter excludes unverified weekend bars from model inputs.
- PR #67 — D1 research source uses per-security TQBR daily-history OHLCV; raw calendar candles retained only for reconciliation.
- PR #68 — manual read-only multi-timeframe collector introduced (Finam intraday and MOEX ISS native frames).
- PR #69 — Finam 401 refresh/retry once; incomplete MOEX M10/W1/MN/QR bars excluded.
- PR #70 — native Finam H1 collection; complete-bar and timezone/no-lookahead validation.
- PR #71 — native official MOEX ISS TQBR D1 collection and D1 close-time validation. Merge commit is current main `a65eeaf...`.
- All above were merged after required CI checks passed. Do not confuse the separate MTF D1 feed with the frozen historical D1 research dataset.

## Prior research report — development only, no confirmed edge
- Last completed research run: `44797994665`; artifact ID `14660240933`; report generated 2026-11-20 19:08 UTC.
- 44/44 tickers; zero history fetch errors; data range 2023-11-20 to 2026-11-19; 31,405 model bars; 37,533 raw calendar candles; 5,869 weekend rows.
- All 44 reconciliation statuses `VALID_WITH_CAVEATS`; 1,237 aggregate date OHLCV mismatches, 419 unassigned raw candles, 2 unmapped weekend bars; all crosschecks `CROSSCHECK_INCONCLUSIVE`. Notably T, PLZL, VTBR, GMKN, TRNFP had higher mismatch counts. Do not erase these caveats or treat crosscheck as passed.
- Prospective holdout: all 44 `WAITING_FOR_PROSPECTIVE_DATA`; zero holdout bars/trades in that run.
- Preliminary development screens: Donchian20 10 ticker unadjusted passes; MACD12x26 7; EMA20x50 0; RSI14Trend50 0; Keltner 0. Global multiple-testing eligible_tests=0; no strategy statistically confirmed.
- Development walk-forward portfolio (normalized equity, not RUB; equal-slot cash-only; no MTM open positions): cap5 -18.81%, max DD -40.12%, 955 trades; cap7 -12.19%, max DD -34.86%, 1,277 trades; cap10 -12.09%, max DD -34.72%, 1,673 trades. Development evidence only, not prospective holdout and not profitability proof.
- Scanner output requirement: signals only (LONG/SHORT), strategy, H1 confirmation and relevant signal parameters. No capital, position sizing, or portfolio allocation unless user asks.

## Current development stage and next actions
1. MTF candle collector and validation are complete for the current run. This is data collection only, not a finished scanner.
2. Build a separate read-only MTF scanner in research repo; do not change frozen cohort, frozen D1 research inputs, holdout, or protected files.
3. Architecture candidate for implementation/research: D1 closed-bar direction/context; H1 closed-bar confirmation; use a lower timeframe trigger only as a separately documented design choice (do not silently assume or optimize it). M10/W1/MN/QR/H2/H4/H8 can initially be diagnostics/context, not mandatory gates.
4. Strict as-of joins: for each candidate signal timestamp, use only the latest D1/H1/lower-TF bar whose native interval has fully ended by that timestamp. Never use current/incomplete bars or future timestamps. Preserve provider provenance and timezone.
5. Develop scanner logic on development data only. Keep the 2026-11-20+ prospective holdout sealed from selection/tuning; only log prospective outputs with frozen rules.
6. Do not output fabricated signals. Generate signal lists only after executing code against actual validated data.
7. Keep all workflows manual/read-only unless specifically authorized; no broker execution.
8. Before each PR merge: inspect changed files against protected list, verify both required CI checks are green on exact current PR head SHA, then merge only if safe.

## How another AI should resume
- Read this section first, then `docs/MULTITIMEFRAME_DATASET_2026-11-21.md`, then the code/workflows named above.
- Start by checking current main SHA and open PRs/workflow status; this handoff can become stale.
- Download artifact run `44861047844` / artifact `14690518588` before its 30-day expiry if you need the full raw candle arrays.
- Continue only in `moex-edge-fast1`. Do not assume any other assistant has the artifact in its local filesystem.
- Do not ask user to repeat details already in this handoff. Provide concise progress in Russian and continue autonomous safe research work.


## 2026-11-21 — D1/H1 read-only scanner prototype (PR #73)
- PR: https://github.com/vkazarin763-cloud/moex-edge-fast1/pull/73
- Branch: `feature/mtf-signal-scanner-20261121`; scanner module `research_agent/mtf_scanner.py`, tests `tests/test_research_mtf_scanner.py`.
- D1 evaluates only the latest fully closed native TQBR D1 bar using the five frozen formulas: Donchian20, EMA20x50, RSI14Trend50, MACD12x26, Keltner20x2ATR. Parameters are unchanged.
- H1 confirmation is informational only: LONG = H1 EMA20>EMA50 and close>EMA20; SHORT = H1 EMA20<EMA50 and close<EMA20. It does not filter, rank, or select strategies.
- H1 bars are bounded by both as_of and the D1 signal bar end; latest H1 timestamp, end, and age at D1 close are reported. Cross-strategy direction conflicts are surfaced, not silently resolved.
- Requires validator PASS with zero issues and matching collector/validator snapshot times. No network calls, account access, order endpoints, or execution imports.
- Workflow `.github/workflows/research-agent-mtf-signals.yml` can be manually dispatched with source run ID, or automatically follows a successful future MTF candle collection. For the existing artifact, after PR #73 merges, manually dispatch it with source_run_id `44861047844`; GitHub MCP cannot dispatch workflows.
- Initial scanner tests passed on earlier head. A later no-lookahead boundary test and workflow were added; final head CI must be rechecked before merge.
- This is a scanner prototype, not an approved strategy-performance cohort. H1 overlay was not tuned against holdout and must remain informational. Actual signal output has not yet been generated from the artifact.
- Since the MTF overlay was specified after the holdout start (2026-11-20), do not retroactively use post-2026-11-20 observations to tune it. Prospective monitoring starts only after the scanner rules are frozen and merged.
