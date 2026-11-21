# MOEX EDGE v2 — isolated single-security core

Status: research-only primitives. No strategy is approved, profitable, or
connected to the v1 scanner or any broker interface.

Implemented in this first increment:
- V2-01 Time-Series Momentum 12–1: positive trailing return is LONG, negative is
  SHORT, with the latest 21 sessions skipped and a 252-session formation anchor.
- V2-03 52-week-high proximity: close divided by the rolling 252-session high.
  It returns a ranking metric only; no long/short threshold has been invented.

Both functions fail closed as `DATA_NOT_READY` unless the caller explicitly
supplies a verified adjusted or verified same-share price-basis status. They
return `INSUFFICIENT_DATA` when the required history is absent. Input bars must
have strictly increasing unique ISO timestamp strings and finite positive
close/high values with high >= close.

The functions are signal/metric primitives only. They do not rebalance monthly,
simulate entries/exits, calculate costs, rank a cross-sectional universe, or
establish profitability. Those steps require separately frozen rules and a
validated data basis. V1 remains untouched.
