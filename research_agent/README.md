# MOEX EDGE — isolated AI Research Agent

This package is deliberately separate from the live stock/futures executors and
from `ai_agent.py`, `ai_trainer.py`, `ai_portfolio.json` and `ai_weights.json`.
It has no broker client, order endpoint, Telegram sender, or production write path.

## Current scope

- Strict OHLCV validation (finite positive prices, valid OHLC relationships,
  non-negative volume, strictly increasing timestamps; gaps are not fabricated).
- A small pre-registered candidate set: Donchian-20 breakout and EMA-20/50 cross.
- Signal is calculated on a completed candle; entry is the next available candle open.
- Conservative intrabar ambiguity: stop is checked before target; stop gaps fill
  at the bar open; target fills at the target level.
- Fees and slippage are charged on both entry and exit.
- One non-overlapping trade per symbol; terminal positions are labelled OPEN and
  excluded from realized performance statistics.
- No parameter optimizer and no production promotion.

## Input format

CSV columns: `timestamp,open,high,low,close,volume`. Timestamp must be ISO-8601.
Each file should contain one instrument and one timeframe, sorted oldest first.

## Important limitations

This is the first isolated research foundation, not a completed autonomous
strategy-discovery service. MOEX ISS ingestion, multi-symbol portfolio simulation,
walk-forward/OOS orchestration, multiple-testing controls, regime analysis and
independent validation are subsequent milestones. Do not interpret example
statistics as a live signal or evidence of profitability.

## Safety boundary

Nothing in this package can submit orders or alter the existing AI Trainer,
virtual trading state, Finam executors, futures executor, scheduled workflows,
or production strategy configuration. Promotion requires independent review
and explicit owner approval.
