# MOEX EDGE autonomous-agent discovery pilot

## What runs

A manual GitHub Actions pilot uses the existing free-tier Groq API and the frozen 44-stock universe.

1. Collects only the current operational D1/H1 lookback through the read-only Finam/MOEX data path.
2. Validates candle chronology, OHLCV and the closed-bar boundary.
3. Runs the deterministic D1/H1 scanner without pre-filtering candidates by research registry.
4. Calls three independent Groq roles: signal hunter, strategy scout and skeptical reviewer.
5. Requires a two-of-three agent consensus for a signal proposal.
6. Drops any AI proposal that is not an exact match to a deterministic candidate.
7. Sends consensus proposals through the deterministic verifier. A confirmed signal still requires a fresh research registry PASS and H1 confirmation.

## What agents can and cannot discover in this first pilot

The first pilot explores the five frozen deterministic strategy families (Donchian20, EMA20x50, RSI14Trend50, MACD12x26 and Keltner20x2ATR) and five existing timeframe configurations (A-E). It can propose which combinations deserve further research and shortlist current signals already found by the scanner.

It does not yet invent arbitrary new indicator formulas. New formula discovery requires a separate constrained strategy DSL and deterministic backtest compiler; an LLM must never turn free-form code into a live strategy.

## Status semantics

- Signal proposals must exactly match a row from the deterministic scanner.
- A two-of-three vote is required before verification.
- Strategy/timeframe hypotheses are marked UNTESTED_RESEARCH_HYPOTHESIS.
- If the registry has no PASS entry, reproducible candidates remain EXPERIMENTAL_STRATEGY_UNAPPROVED.
- Confirmed means exact deterministic reproduction + fresh registry PASS + H1 confirmation. It is not a production or execution authorization.

## Safety and cost

- Free-tier Groq model by default; three sequential API calls per pilot.
- Manual dispatch only for the initial pilot; no unattended schedule is enabled yet.
- Read-only market data. No broker account, order, position, or execution APIs.
- AI receives a compact candidate snapshot, not raw candle history.
- Full historical backtests remain in the separate deterministic research workflow.
