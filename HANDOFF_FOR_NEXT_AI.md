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
- No broker API calls, live orders, secret reads/changes, or Actions variable changes were performed in this follow-up.

- CI follow-up completed successfully after the code, tests, and journal updates: run `44141464912`, job `unit-tests`, compile step passed, `Ran 14 tests`, `OK`. This run corresponds to commit `a19e63308cef5dec7345abcc87abd73e87380663`.
