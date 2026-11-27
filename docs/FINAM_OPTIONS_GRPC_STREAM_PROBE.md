# Finam options gRPC stream probe

A bounded, read-only experiment to compare live market-data streams with the existing REST snapshot collector.

## Run

GitHub Actions → **Finam Options gRPC Stream Probe (Read Only)** → Run workflow.
Default capture is 120 seconds. The artifact is retained for 30 days.

## Streams

- `SubscribeQuote` for both option symbols.
- `SubscribeOrderBook` per symbol.
- `SubscribeLatestTrades` per symbol.

Uses the official `finam-sdk==2.19.1` package and the existing `FINAM_API_SECRET` repository secret.

## Interpretation

Every event has a client-side `received_at_utc`; provider timestamps remain inside the protobuf payload. Compare those separately. Order-book stream messages can be incremental updates; honor `is_data_snapshot` and do not treat a delta as a complete book.

## Safety

Only market-data subscriptions are called. No account, order, cancel, or execution APIs are imported or invoked. No secret/JWT is written to the artifact. This probe does not place trades and does not establish fillability or profitability.
