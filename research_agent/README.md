# MOEX EDGE — isolated AI Research Agent

This package is deliberately separate from the live stock/futures executors and
from `ai_agent.py`, `ai_trainer.py`, `ai_portfolio.json` and `ai_weights.json`.
It has no broker client, order endpoint, Telegram sender, or production write path.

## Current scope

- Strict OHLCV validation (finite positive prices, valid OHLC relationships,
  non-negative volume, strictly increasing timestamps; gaps are not fabricated).
- Timestamp policy: a dataset must use either all-naive exchange-local timestamps
  (the format returned by MOEX ISS) or all timezone-aware timestamps. Mixed
  aware/naive timestamps are rejected rather than silently compared.
- MOEX additional weekend sessions can produce valid Saturday/Sunday daily candles.
  These are retained as separate calendar-day bars; they are not yet re-aggregated
  into the next ordinary trading day. Therefore `max_bars` counts returned bars,
  not Monday-Friday trading days. Calendar-aware session aggregation remains a
  methodology item for review.
- A fixed, pre-registered candidate set: Donchian-20 breakout, EMA-20/50 cross,
  RSI-14 trend momentum, MACD-12/26 crossover and Keltner-20/2ATR breakout. Parameters are not fitted on the evaluation data.
- Signal is calculated on a completed candle; entry is the next available candle open.
- Conservative intrabar ambiguity: stop is checked before target; stop gaps fill
  at the bar open; target fills at the target level.
- Fees and slippage are charged on both entry and exit.
- Each candidate strategy is simulated independently with non-overlapping trades; terminal positions are labelled OPEN and excluded from realized performance statistics.
- No parameter optimizer and no production promotion.

## Input format

CSV columns: `timestamp,open,high,low,close,volume`. Timestamp must be ISO-8601.
Each file should contain one instrument and one timeframe, sorted oldest first.

## Important limitations

The read-only runner (`python -m research_agent.cli --from YYYY-MM-DD --till YYYY-MM-DD`)
fetches daily candles from MOEX ISS for the fixed 44-symbol first-listing universe
and produces a JSON report. `moex_iss.py` paginates responses, validates OHLCV and
rejects duplicate timestamps without fabricating missing candles. Every analyzed ticker also receives a `data_quality` section with requested/actual date boundaries, zero-volume and weekend bar counts, history sufficiency, and long calendar-gap candidates. A calendar-gap candidate is deliberately not called a missing session: the MOEX holiday, listing and suspension calendars are not yet joined. `validation.py`
evaluates fixed candidates on sequential walk-forward folds with expanding indicator
history and explicit minimum-sample/stability gates. A pass is labelled
`DEVELOPMENT_SCREEN_PASS_UNADJUSTED`: it is only a development shortlist, not an
independent or multiplicity-adjusted result. The separate prospective holdout
is the only stage that applies HAC inference, block-bootstrap intervals and
Holm correction.

This is not yet a fully validated discovery system. Multi-symbol portfolio simulation,
regime analysis and independent adversarial validation remain outstanding. The
prospective holdout includes HAC inference, moving-block bootstrap intervals and
Holm correction, but those safeguards do not replace independent replication or
portfolio-level testing. Exploratory statistics are not live signals or evidence
of profitability.

## Prospective validation protocol

The strategy definitions and parameters are frozen as candidate set
`v1-frozen-2026-11-19` for prospective evaluation. Reports include this version
and the exact execution assumptions (fees, slippage, stop, target and maximum
bar horizon) so later cohorts cannot silently reuse the same label.
The historical research period ends before **2026-11-20**; that date is the
boundary for the untouched holdout. The loader retains at least three full
years of pre-cutoff development history even after the normal rolling fetch
window moves forward. Data on or after that date is
evaluated separately and is never included in the development walk-forward or
its doubled-cost stress test. Until new post-cutoff candles arrive, each ticker
must report `WAITING_FOR_PROSPECTIVE_DATA`; previously reviewed history is not
relabelled as an independent holdout.

The prospective screen requires at least 30 closed trades per ticker/strategy.
It reports a one-sided Newey-West HAC test of mean net trade return, a 95%
moving-block bootstrap confidence interval, and Holm-Bonferroni family-wise
error correction over the full selected universe × five pre-registered
strategies (220 hypotheses for the default 44-symbol universe). The confidence
interval and corrected test are both required for a research-pass label.
These are statistical screening safeguards, not proof of future profitability.
The holdout is prospective and cumulative; keep the frozen start date and
candidate definitions unchanged while collecting it.

## Safety boundary

The scheduled research workflow is read-only and has no broker secrets. Nothing in this package can submit orders or alter the existing AI Trainer,
virtual trading state, Finam executors, futures executor, scheduled workflows,
or production strategy configuration. Promotion requires independent review
and explicit owner approval.
