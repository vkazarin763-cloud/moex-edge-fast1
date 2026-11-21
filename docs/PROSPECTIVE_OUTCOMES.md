# Prospective outcome ledger

This component turns the append-only MTF signal journal into an append-only
journal of closed prospective outcomes. It is separate from the HISTORICAL
trade archive and never backfills pre-holdout signals.

## Rules

- Only cohort v1-frozen-2026-11-19 signals whose D1 signal candle is dated
  2026-11-20 or later are eligible.
- Each signal must map to its exact native MOEX ISS TQBR D1 candle. Missing
  signal candles or unavailable/invalid D1 source data fail closed.
- All prospective signals for a symbol are replayed together through the
  existing research_agent.core.backtest engine. Its per-strategy non-overlap
  rule is preserved; signals skipped because an earlier trade occupies that
  strategy stream are counted separately.
- Entry is the next D1 open. Frozen stop, target, max holding period, fees,
  slippage, gap and same-bar stop-first rules come from BacktestConfig.
- Open trades and signals waiting for the next open are not appended to the
  closed-outcome ledger. They are recalculated from the latest candle snapshot
  on the next run.
- Once a closed outcome is written, its deterministic identity and complete
  payload are immutable. If a later replay produces a different payload, the
  updater fails closed rather than rewriting the record.
- Only CLOSED rows with a non-null net return enter closed-trade summaries.
  Aggregate sum of trade returns is not a portfolio return.

## Storage

The existing serialized ledger workflow updates two files on the isolated
moex-edge-signal-ledger branch:

- signal-ledger/events.jsonl — immutable first-observed prospective signals.
- signal-ledger/prospective-outcomes.jsonl — append-only closed outcomes,
  each tagged data_origin: PROSPECTIVE.

The workflow downloads the exact candle artifact belonging to the collector
run that produced the scanner report. It does not use a newer, unrelated
snapshot. No broker secrets or endpoints are used.

## CLI

python -m research_agent.prospective_outcomes --signals-ledger signal-ledger/events.jsonl --candles moex_edge_multi_timeframe_candles.json --outcomes-ledger signal-ledger/prospective-outcomes.jsonl

The report is diagnostic only. It is not a broker execution record, not a
profitability claim and not portfolio accounting.
