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

## Deliberate limits

- This component records signal creation only; it does not calculate returns,
  exits, trade outcomes, or profitability.
- No historical signals are backfilled by inference. Only scanner reports
  explicitly passed to the writer are eligible.
- The JSONL file is append-only at the application layer. Durable GitHub
  storage, serialized writes, branch permissions and retention are a separate
  workflow integration and are not enabled by this change.
- The writer is local-file-only: no network, broker, token, account or order
  interfaces.
- The frozen cohort, holdout boundary, scanner formulas and execution rules
  are unchanged.

## CLI

`python -m research_agent.signal_ledger --report moex_edge_mtf_signals.json --ledger signal-ledger/events.jsonl`

Run the writer only against a dedicated ledger checkout/path after the
persistence workflow has been reviewed and enabled. Do not point it at the
research datasets or legacy Finam execution state.
