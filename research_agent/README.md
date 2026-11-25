# MOEX EDGE — Finam-only research and signal pipeline

This package is isolated from the live stock/futures executors and from
`ai_agent.py`, `ai_trainer.py`, portfolio state, and production strategy
configuration. The research and scanner workflows are read-only: they do not
access broker accounts, positions, orders, or execution endpoints.

## Active market-data source

**Finam Trade API is the only market-data provider in the active research and
D1/H1 signal pipeline.**

- D1 research uses native Finam `TIME_FRAME_D` candles for the 365-calendar-day
  window from 2025-11-20 through 2026-11-19.
- The frozen holdout begins 2026-11-20. Bars on or after that date are excluded
  from strategy selection, parameter tuning, calibration, and historical
  performance metrics.
- The D1/H1 inference collector fetches both timeframes directly from Finam.
  H1 is limited to Finam's documented 30-calendar-day history window.
- Explicit `is_data_snapshot=true` bars are excluded. Unknown snapshot flags
  are retained and counted; they are not silently assumed complete.
- OHLCV, timestamps, ordering, symbol/MIC identity, request boundaries, and
  completed-bar status are validated. Missing bars are not fabricated.
- There is no MOEX ISS fallback, resampling, provider blending, interpolation,
  or gap filling in the active collector or signal scanner.
- Exchange-qualified symbols use Finam's `@MISX` MIC, for example
  `SBER@MISX`.

Finam documents a maximum 365-day D1 lookback and 30-day H1 lookback in the
client adapter. The collector enforces those limits locally.

## Research and scanner workflow

The scheduled/manual workflow **MOEX EDGE Autonomous Research (Finam Only,
Read Only)** calls the reusable **MOEX EDGE Finam D1 Technical Analysis
Research (Read Only)** workflow. It collects one year of D1 data for the fixed
44-symbol first-listing universe and evaluates the pre-registered technical
candidate set with fees, slippage, next-open execution, and Chandelier Exit.

The report includes source coverage, OHLCV audit information, dataset hashes,
trade ledgers, and doubled-cost diagnostics. Pooled trade statistics are not
portfolio returns and do not establish profitability.

The current one-year exploratory report does not yet contain four independent
walk-forward folds per ticker/strategy/direction. Therefore
`finam_strategy_registry.py` deliberately marks every strategy
`INSUFFICIENT_DATA` and never approves a candidate. The scanner may run only
when the 44-symbol Finam data coverage is complete, but it will filter out all
strategies until a separate Finam-only walk-forward evaluation satisfies every
frozen gate:

- at least 30 closed trades;
- all four walk-forward folds have at least five trades;
- positive average net return;
- profit factor above one;
- positive result under doubled costs.

These gates must not be weakened merely to produce signals. A zero-signal
result is valid when no candidate has sufficient evidence.

The multi-timeframe collector supports Finam-native D1 and intraday bars.
The operational signal workflow requests D1/H1 only. The scanner requires
Finam Trade API as the source for both frames, validates timestamps and
no-lookahead alignment, and does not calculate capital, position sizing,
portfolio allocation, or broker orders.

## Frozen holdout and inference boundary

The strategy research cutoff is 2026-11-19 inclusive; the untouched holdout
starts 2026-11-20. Post-cutoff observations may be used for current inference
with already-frozen formulas, but their outcomes must not be used to select
strategies, tune parameters, calibrate probabilities, or report performance
metrics. Experimental probabilities remain explicitly uncalibrated and must
not be presented as reliable probabilities.

## Legacy code

Older MOEX ISS research modules and their offline tests remain in the repository
for historical regression/reference purposes only. The old MOEX ISS and
cross-provider Actions workflows have been retired. They are not called by the
active Finam-only research, candle collection, registry, or signal-scanning
workflows. Do not reactivate them as a fallback or mix their data into Finam
reports.

## Credentials and safety

Supply `FINAM_API_TOKEN` as a GitHub Actions repository secret. If Finam has
issued a source application ID, supply `FINAM_SOURCE_APP_ID` as a separate
secret. Never put credentials in workflow inputs, commits, reports, or chat.
The client does not expose account, order, position, or execution methods.
Promotion to production requires independent review and explicit owner
approval.
