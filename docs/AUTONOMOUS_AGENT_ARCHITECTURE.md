# MOEX EDGE autonomous-agent architecture

## Trust boundaries

1. **Research agents propose; they do not publish authoritative signals.** Their output is an untrusted JSON proposal report.
2. **The deterministic market-data pipeline is the signal authority.** It checks completed candles, OHLCV, timestamps, indicator formulas and the no-lookahead boundary.
3. **The strategy registry is the strategy-quality authority.** A proposal remains experimental until its strategy passes the independent walk-forward and doubled-cost research gate.
4. **H1 confirmation is mandatory for a confirmed signal.** An otherwise reproducible proposal with missing or negative H1 confirmation is not confirmed.
5. **No broker/execution integration.** The system remains read-only.

## Signal states

- `CONFIRMED`: exact match to a deterministic signal, strategy registry PASS, and H1 confirmation.
- `VERIFIED_SIGNAL_H1_NOT_CONFIRMED`: deterministic signal and research PASS, but H1 confirmation is absent.
- `EXPERIMENTAL_STRATEGY_UNAPPROVED`: signal reproduces, but the strategy has not passed the research gate.
- `REJECTED_NOT_REPRODUCED`: the deterministic scanner cannot reproduce the agent's exact symbol/direction/strategy/closed-D1-bar timestamp.

The agent cannot supply authoritative prices, indicator values, backtest metrics, or approval status. Those are taken only from deterministic artifacts.

## Data efficiency

- The operational scan should request only selected timeframes and the warm-up window required by their indicators.
- A persistent candle cache should retain validated history and fetch only newly available bars, with periodic reconciliation.
- Historical multi-year downloads belong to the separate research/backtest pipeline and should run only for strategies/configurations selected for testing.
- Cache contents must be invalidated/reconciled when source, board, instrument mapping, calendar, corporate-action basis or schema changes.

## Delivery stages

This PR introduces the strict proposal-to-verification contract and offline tests. It does not yet schedule LLM calls or change the active scanner. The next stage is to connect free-tier research agents to this contract, then run a no-signal smoke test before enabling periodic signal discovery.
