# Finam options gRPC stream quality probe

A bounded, read-only capture that measures per-instrument freshness and deduplicates repeated provider timestamps. It is a data-quality diagnostic, not a trading signal or execution test.

## Run

GitHub Actions → **Finam Options gRPC Stream Probe (Read Only)** → Run workflow.
Default capture is 180 seconds (allowed 30–300). The artifact is retained for 30 days.

The default option set includes both CALL and PUT for GAZP and SBER:
- `GZ100CL6@RTSX` — GAZP CALL
- `GZ100CX6@RTSX` — GAZP PUT
- `SR290CL6@RTSX` — SBER CALL
- `SR290CX6@RTSX` — SBER PUT

`SBER@MISX` remains a control symbol for the underlying share quote stream.

## Metrics

The JSONL artifact preserves raw gRPC envelopes and adds normalized per-instrument records:
- quote snapshot vs update counts;
- unique provider timestamps and duplicate/repeated timestamps;
- fresh unique quote updates (provider timestamp no more than 60 seconds old at client receipt) vs stale updates;
- per-instrument order-book snapshots, delta messages, delta row counts, action counts, and row timestamp ages;
- trade event counts;
- unary `LastQuote` snapshots and token market-data entitlements.

Counts are per instrument item, not per gRPC envelope. A repeated quote snapshot or an old quote repeated by the server is not treated as fresh market activity. The 60-second threshold is a diagnostic convention, not a guarantee of executable prices. Provider timestamps are retained separately from client receipt timestamps.

## Interpretation

- Frequent SBER control updates but no fresh option updates: the connection is alive, but option quotes are inactive, stale, or not being delivered.
- Fresh option quote updates and unique order-book deltas: the option stream is demonstrably delivering current changes during the capture.
- Snapshots without fresh updates: subscription initialization succeeded, but ongoing freshness is not established.
- No trade events in a short capture does not prove that the trade stream is broken; it may simply mean no trades occurred.

## SDK and safety

Uses the official Finam Python SDK pinned to published `finam-sdk==2.24.0` and the existing `FINAM_API_SECRET` repository secret. A separate import check runs before connection.

Only token metadata and market-data RPCs are called. No balances, positions, account IDs, orders, cancellations, or execution APIs are queried. The JWT and secret are never written to the artifact. The token details response reports `readonly`; this probe itself does not invoke trading APIs.

A successful stream does not prove fillability, profitability, or suitability for live trading. All strategy and live-execution work remains out of scope.
