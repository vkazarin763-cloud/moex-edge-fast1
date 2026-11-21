# MOEX EDGE v2 — isolated research core

Status: research-only primitives. No strategy is approved, profitable, or
connected to the v1 scanner or any broker interface.

## Implemented primitives

- **V2-01 Time-Series Momentum 12–1:** positive trailing return is LONG, negative
  is SHORT; uses a 252-session anchor and skips the latest 21 sessions.
- **V2-03 52-week-high proximity:** close divided by the rolling 252-session high.
  This is a ranking metric only; no directional cutoff is invented.
- **V2-02 Cross-Sectional Momentum 12–1:** ranks an explicitly supplied
  point-in-time universe; top quintile is LONG_CANDIDATE and bottom quintile is
  SHORT_CANDIDATE. All constituents must share the same completed session
  calendar through the formation date; a missing session cannot silently shift
  one security's return window.
- **V2-04 Relative Strength vs IMOEX:** compares 6-month security return with
  IMOEX return while skipping the latest 21 sessions. Formation and both anchor
  timestamps must match exactly. The metric is excess return, not
  beta-adjusted alpha and not a standalone directional signal.

## Hypothesis registry

`registry.py` records the five v2 hypotheses and their implementation state. The first four have research primitives or metrics only; none is validated or approved. Pairs trading is explicitly blocked until adjusted prices, point-in-time pair membership, liquidity/spread data, shortability and borrow-cost assumptions are available. The registry is descriptive metadata, not a promotion gate.

## Data and safety contract

The price-based functions fail closed as `DATA_NOT_READY` unless the caller
explicitly supplies a verified adjusted or verified same-share price-basis
status. They return explicit insufficient-data or unsynchronized-data states
when history or exact session alignment is absent. Input bars require strictly
increasing unique ISO-8601 timestamps and finite positive close/high values
with high >= close.

Cross-sectional membership is supplied by the caller as a point-in-time
universe. Price-basis verification is supplied separately for each ticker;
unverified constituents are excluded and the minimum verified-universe gate
must still be met. Relative strength requires separate verification for both
the security and IMOEX. The module does not reconstruct historical listings
from today's constituents. See `PRICE_BASIS_GATES.md` for the evidence contract. The 52-week-high and relative-strength functions do not invent
trading thresholds. These modules do not rebalance, simulate execution, apply
fees/slippage, or establish profitability.

No live scanner integration, broker interface, order path, or credentials are
present. V1 remains untouched.
