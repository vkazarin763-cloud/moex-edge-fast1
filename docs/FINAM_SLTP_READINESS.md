# Finam protective orders — readiness and safety

## Current implementation

The executor prepares a paired Finam SL/TP order after it has confirmed the actual filled quantity and weighted-average execution price.

The current project policy remains unchanged:
- Stop loss: 3% from the actual average fill price.
- Take profit: 5% from the actual average fill price.
- LONG: SL below fill, TP above fill.
- SHORT: SL above fill, TP below fill.
- Both SL and TP quantities equal the confirmed executed share quantity.
- Prices are rounded directionally to the instrument's actual Finam tick size.

The percentages are centralized in `finam_executor.py` and must remain aligned with `REC_SL_PCT` and `REC_TAKE_PCT` in `moex_edge_fast_33.py`. This patch does not change strategy rules or optimize these percentages.

## Finam API contract

The official REST documentation defines `POST /v1/accounts/{account_id}/sltp-orders`, describes `side` as the side for both protective orders, and shows `SIDE_BUY` in its example with a lower stop and a higher take-profit price. The executor therefore maps the protected LONG position to `SIDE_BUY` and SHORT to `SIDE_SELL`.

The executor first waits for the account snapshot to show the exact signed position quantity (positive LONG / negative SHORT) confirmed by trade history. It does not submit SL/TP while the account snapshot is missing, stale, or inconsistent. Protective orders explicitly use `VALID_BEFORE_GOOD_TILL_CANCEL` (the API default is also GTC). It uses explicit share units (`SLTP_QTY_MEASURE_VALUE`) and validates broker read-back:
- order ID and active status;
- symbol and protected-position side;
- exact SL and TP quantities;
- exact SL and TP prices.

An ambiguous POST is reconciled by `client_order_id`; it is never blindly resubmitted. A rejected, unknown, or mismatched read-back stops processing subsequent signals and raises an alert.

## Important unresolved broker check

This mapping is supported by the official API example, but it has **not** been validated with a Finam sandbox or a successful real SL/TP placement. The previous live T entry was accepted while Finam rejected its SL/TP request with error `[666] Attention! An uncovered position may arise/increase.`

Do not enable live trading until Finam confirms the meaning of the SL/TP `side` field for both LONG and SHORT positions and the broker accepts and reports the expected protective order state.

## Operational safety

- Manual executor workflow forces `FINAM_DRY_RUN=true`.
- Scheduled scanner/executor workflow also forces `FINAM_DRY_RUN=true`.
- The executor branch adds a second code-level gate: live mode additionally requires `FINAM_LIVE_TRADING_ENABLED=true`.
- The read-only Finam audit checks the previously traded `T@MISX` position and active orders, and validates lot/tick/trading permissions for the 44-stock universe.
- No real order, stop, take-profit, cancellation, or modification is sent by CI tests or the read-only audit.

If Finam rejects SL/TP after a position is filled, this implementation stops processing new signals and alerts for manual reconciliation. It does not silently claim that the position is protected, and it does not automatically send an emergency market close.

## Verification boundary

Unit tests cover request payload construction, LONG/SHORT mapping, rounding, partial fills, ambiguous responses, read-back mismatches, and account-audit parsing. Unit tests do not prove that Finam will accept a live SL/TP order. That final broker-side confirmation remains a release blocker.
