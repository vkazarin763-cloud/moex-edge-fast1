# MOEX EDGE — isolated AI Research Agent

This package is deliberately separate from the live stock/futures executors and
from `ai_agent.py`, `ai_trainer.py`, `ai_portfolio.json` and `ai_weights.json`.
It has no broker client, order endpoint, Telegram sender, or production write path.

## Current scope

- Strict OHLCV validation (finite positive prices, valid OHLC relationships,
  non-negative volume, strictly increasing timestamps; gaps are not fabricated).
- A fixed, pre-registered candidate set: Donchian-20 breakout, EMA-20/50 cross, RSI-14 trend momentum, MACD-12/26 crossover and Keltner-20/2ATR breakout. Parameters are not fitted on the evaluation data.
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
rejects duplicate timestamps without fabricating missing candles. `validation.py`
evaluates fixed candidates on sequential walk-forward folds with expanding indicator
history and explicit minimum-sample/stability gates.

This is not yet a fully validated discovery system. Multi-symbol portfolio simulation,
formal multiple-testing correction, bootstrap confidence intervals, regime analysis
and independent adversarial validation remain outstanding. Exploratory statistics
are not a live signal or evidence of profitability.

## Safety boundary

The scheduled research workflow is read-only and has no broker secrets. Nothing in this package can submit orders or alter the existing AI Trainer,
virtual trading state, Finam executors, futures executor, scheduled workflows,
or production strategy configuration. Promotion requires independent review
and explicit owner approval.
