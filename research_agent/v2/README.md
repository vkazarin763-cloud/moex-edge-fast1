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


## Autonomous hypothesis discovery — first isolated slice

`discovery.py` adds a deterministic, data-driven rule generator. It accepts a
caller-supplied feature panel (feature series may be any validated numeric
market descriptors; no indicator names are hard-coded), estimates feature
thresholds from explicit formation indices only, and emits LONG/SHORT
single-feature rules plus two-feature conjunctions. Thresholds use configurable
quantiles. Candidate IDs are deterministic, missing feature values fail closed,
and a hard candidate cap prevents combinatorial growth.

The generator deliberately does **not** accept forward returns, so outcomes
cannot influence threshold selection or candidate construction. The caller
must keep formation indices chronological and strictly before the evaluation
window. This first slice generates entry hypotheses only: it does not yet
define exits, run backtests, perform multiple-testing correction, or promote
strategies. Those are separate stages and must be added before any candidate
can be described as tested or useful.

Tests: `tests/test_research_agent_v2_discovery.py`. No v1 scanner, frozen
cohort, holdout, workflow, broker, or production file is changed.


## OHLCV-derived feature panel

`features.py` now derives a generic feature panel directly from validated
OHLCV bars. It includes multi-horizon returns, candle body/range/wicks/close
location, opening gap, relative volume versus the *prior* volume window,
range expansion versus prior ranges, realized close-to-close volatility, and
trend efficiency. Feature arrays align with input bars; unavailable warm-up
values remain `None` so they cannot be mistaken for zero.

The extractor validates strictly increasing unique ISO-8601 timestamps,
positive finite OHLC prices, valid high/low relationships, and finite
non-negative volume. Every feature at row t uses only information available
through that bar's close. The test suite includes a future-mutation check:
changing later bars must not change any earlier feature values.

The output mapping can be passed directly to `generate_hypotheses()`.
This connects raw-bar descriptors to candidate generation without requiring
preselected indicator names. It still does not constitute a complete discovery
loop: exits, execution-aware evaluation, multiple-testing correction,
walk-forward/holdout validation, and promotion gates remain unimplemented.


## Causal execution evaluator

`execution.py` evaluates one entry hypothesis and an independent exit rule.
Signals are evaluated after a completed bar and filled at the next bar open.
Adverse slippage is applied to each fill and commission is charged on both
entry and exit notionals. The simulator permits one position at a time, with no
pyramiding, capital sizing, portfolio allocation, broker access, or orders.

Positions still open at the end of the supplied history are reported separately
and excluded from closed-trade metrics; a signal on the final bar is not filled.
The evaluator reports closed-trade win rate, mean/median net return, profit
factor (only when gross losses exist), and individual trade records. It does
not approve strategies. Multiple-testing correction and genuinely unseen
walk-forward/holdout evaluation remain mandatory before any performance claim.


## Multiple-testing correction

`multiple_testing.py` implements Holm-Bonferroni step-down correction for
an explicitly supplied, complete hypothesis family. It validates p-values,
preserves candidate IDs and input order, reports adjusted p-values and
family-wise rejection decisions, and records the family size and alpha.

The correction accepts externally computed p-values; it does not derive them
from returns or trade metrics. The caller must register the full tested family
before examining results and include every tested candidate, not only winners.
Holm controls family-wise error under arbitrary dependence only if each
marginal p-value is valid. In particular, overlapping trades, serial
dependence, repeated parameter searches, and data snooping require a
statistically appropriate test and research protocol. This module alone does
not solve those problems and never marks a strategy approved.

Tests: `tests/test_research_agent_v2_multiple_testing.py`.


## Dependence-aware inference

`bootstrap.py` implements a circular moving-block bootstrap test of the
chronological mean net return against zero. It resamples contiguous blocks,
centres the series under the null, uses a finite-resample plus-one two-sided
p-value, and reports a percentile confidence interval. The seed is explicit
and deterministic. A minimum sample size and valid block-length range are
enforced.

This is an inference primitive, not an automatic profitability verdict.
Block length must be varied in sensitivity analysis. Circular wrapping is an
approximation; structural breaks, volatility clustering, overlapping trades,
cross-security dependence, and strategy selection can require more careful
methods (for example, synchronized panel/block resampling or a pre-registered
reality-check procedure). The test assumes the caller supplies chronological
observations and does not infer the correct sampling unit. Apply Holm to the
complete pre-declared hypothesis family only after producing valid marginal
p-values. Independent walk-forward and holdout evaluation remains mandatory.

Tests: `tests/test_research_agent_v2_bootstrap.py`.


## Formation-driven autonomous optimization

The current pipeline now has a distinct optimization stage between candidate
generation and later validation:

1. Generate up to 200 data-driven entry rules per symbol from the formation
   window, using the existing balanced feature/quantile/operator generator.
2. Generate up to two formation-only exit alternatives for each entry rule.
3. Evaluate the entry/exit pairs on the formation history with next-open fills,
   commission and adverse slippage.
4. Rank pairs using mean net trade return shrunk for small samples and penalized
   for trade-sequence drawdown. Keep the best exit for each distinct entry and
   retain up to five entries per direction.
5. Freeze that shortlist and evaluate it only on the later chronological
   validation window. Validation returns are never used to tune or rank rules.
6. Apply the global Holm correction to the selected validation family across
   symbols and rolling folds. Underpowered selected rules remain visible but
   cannot be promoted.

This is genuine historical parameter/rule optimization over the generated
candidate grid, not proof of future profitability. The current generator still uses quantile-based one- and two-feature
conditions; evolutionary mutations and three-way interactions remain future
search-space extensions. Rolling reports now retain formation optimization
metrics so selected rules can be audited against their later validation results. The previously reported MOEX pilot predates
this optimizer and must not be presented as its result.

The search does not require new candles. The 2026-11-20 sealed row remains
excluded. No strategy approval, capital sizing, broker access or live orders
are introduced.

Focused tests: `tests/test_research_agent_v2_pipeline.py`.
