# MTF signal ledger — design and safety boundary

The append-only signal ledger is separate from the frozen research dataset and
from every broker/execution component.

## Event identity and stored fields

One event is identified by SHA-256 over the frozen cohort version, symbol,
strategy, direction and native D1 candle end. The first observed record stores
the complete scanner signal payload plus the report's generated/as-of UTC
timestamps. This preserves the original D1 parameters and causally aligned H1
snapshot.

Repeated scans of the same event are idempotently skipped. If a repeated event
identity carries a different signal payload, the writer fails closed instead
of rewriting history. Malformed existing JSONL also stops the writer without
repairing or truncating it.

## Durable storage

The workflow **MOEX EDGE Persist MTF Signal Ledger (Read Only)** runs only after
a successful scanner workflow_run from the default `main` branch. It downloads
the scanner artifact from that exact completed run, validates that exactly one
report is present, and appends events to the dedicated
`moex-edge-signal-ledger` branch. Writes are serialized with GitHub Actions
concurrency; the scanner's artifact remains a separate 30-day diagnostic copy.
The data branch is provisioned separately and contains the ledger file, not
research code changes.

The workflow has `actions: read` and `contents: write` permissions because it
must commit the durable ledger. It does not read secrets or access any broker
interface. It never triggers on pull_request or workflow_dispatch.

## Deliberate limits

- This component records signal creation only; it does not calculate returns,
  exits, trade outcomes, or profitability.
- No historical signals are backfilled by inference. Only reports processed
  after this workflow is enabled are eligible.
- The JSONL file is append-only at the application layer. Conflicting repeated
  signal payloads and malformed ledger history stop the writer.
- The frozen cohort, holdout boundary, scanner formulas and execution rules
  are unchanged.
- The legacy Finam signal state and all executor workflows are unrelated and
  must not be used as this ledger's storage.

## CLI

`python -m research_agent.signal_ledger --report moex_edge_mtf_signals.json --ledger signal-ledger/events.jsonl`

The CLI is local-file-only. The GitHub workflow supplies the report and the
dedicated data branch.
