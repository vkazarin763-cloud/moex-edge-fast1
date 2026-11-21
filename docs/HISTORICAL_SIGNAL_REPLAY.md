# Historical signal replay (development only)

The historical replay is a separate diagnostic path. It does **not** write to
`signal-ledger/events.jsonl`, alter the frozen candidate cohort, or count as
prospective holdout evidence.

## Run

```bash
python -m research_agent.multi_timeframe_validation \
  --input moex_edge_multi_timeframe_candles.json \
  --output moex_edge_multi_timeframe_validation.json

python -m research_agent.historical_replay \
  --candles moex_edge_multi_timeframe_candles.json \
  --output moex_edge_historical_simulation.json \
  --cutoff-exclusive 2026-11-20 \
  --exclude-symbols T
```

The cutoff is exclusive: D1 candles dated on or after 2026-11-20 are not used.
The frozen core signal formulas are evaluated on completed D1 bars, with entry
at the next available D1 open. Outcomes are directional raw returns at 1, 5,
10, and 20 subsequent D1 bars; the entry bar counts as bar 1. MFE/MAE is
calculated over the first 20 D1 bars from entry.

## Guardrails and limitations

- The tool calls `research_agent.core.generate_signals`; it does not copy or
  modify the registered strategy formulas.
- It requires native MOEX ISS TQBR D1 history and validates OHLCV chronology.
- `T` is excluded by default because its known 10:1 conversion on 2026-04-17
  falls inside the sample and no automatic price adjustment is permitted.
- H1 confirmation is explicitly marked unavailable: the current H1 collector
  retains only a recent 30-calendar-day window, so historical H1 alignment
  cannot be reconstructed for this sample.
- Gross returns omit fees, slippage, spread, liquidity, and execution effects.
- Signals are independent observations for descriptive purposes. They may
  overlap; this is not a portfolio simulation and has no position sizing.
- Incomplete horizons remain pending; they are not treated as losses or zeros.
- Do not use this replay to tune the frozen cohort or make profitability claims.

The live append-only signal ledger remains reserved for first observations
from the prospective scanner. Historical replay artifacts are separate.
