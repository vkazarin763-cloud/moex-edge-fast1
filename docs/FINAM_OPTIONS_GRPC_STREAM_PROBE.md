# Finam options gRPC stream probe

A bounded, read-only experiment to compare live market-data streams with unary quote snapshots and token market-data entitlements.

## Run

GitHub Actions → **Finam Options gRPC Stream Probe (Read Only)** → Run workflow.
Default capture is 120 seconds. The artifact is retained for 30 days.

## SDK and diagnostics

Uses the official Finam Python SDK, pinned to the published `finam-sdk==2.24.0` release, and the existing `FINAM_API_SECRET` repository secret. A separate import check runs before any connection attempt.

The probe records:
- `TokenDetails` market-data permissions (quote level, MIC/region, delay), but not the JWT or account identifiers;
- unary `LastQuote` snapshots for the option symbols;
- a control `LastQuote` and `SubscribeQuote` stream for `SBER@MISX`, to distinguish an options-symbol issue from a general streaming issue;
- option `SubscribeQuote`, `SubscribeOrderBook`, and `SubscribeLatestTrades` events;
- both gRPC exceptions and Finam stream-level errors carried inside protobuf responses.

## Interpretation

Every stream event has a client-side `received_at_utc`; provider timestamps remain inside the protobuf payload. A successful unary snapshot does not prove that the streaming feed is delivering updates. A control-symbol stream event with no option events points toward option-specific eligibility/activity; no events for either control or options, despite successful unary snapshots, points toward the streaming path or market-data service. Token permissions and RPC errors must be read alongside event counts.

## Safety

Only market-data subscriptions and token metadata are called. No balances, positions, account IDs, orders, cancellations, or execution APIs are queried. No secret/JWT is written to the artifact. This probe does not place trades and does not establish fillability or profitability.
