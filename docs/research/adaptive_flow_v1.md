# MOEX EDGE Adaptive Flow v1 — research specification

Status: PROPOSED, NOT BACKTESTED, NOT APPROVED FOR SIGNALS OR TRADING.

## Purpose

A single, symmetric LONG/SHORT price-structure hypothesis. This is deliberately not another RSI/EMA/MACD combination. The idea is to trade a failed range breakout (liquidity sweep / false breakout) back into the prior range.

## Fixed rules

All calculations use completed native Finam candles only. No resampling, no source blending, no look-ahead.

### Setup

For each symbol and completed D1 candle t:

- Define the prior range from the 20 completed candles immediately before t:
  - prior_high = max(high[t-20:t])
  - prior_low = min(low[t-20:t])
- LONG setup (failed downside breakout): low[t] < prior_low AND close[t] > prior_low.
- SHORT setup (failed upside breakout): high[t] > prior_high AND close[t] < prior_high.
- Require relative volume: volume[t] >= 1.5 * median(volume[t-20:t]).
- The signal is evaluated only after candle t is complete.
- Enter at the next eligible D1 candle open. No same-candle fills.

### Initial risk

- LONG invalidation: signal-candle low.
- SHORT invalidation: signal-candle high.
- Add a fixed buffer equal to 0.10 * ATR(14) measured as of signal close, beyond the invalidation level.
- If the next open has already crossed the invalidation level, skip the trade.

### Exit

- Initial target: midpoint of the prior 20-candle range.
- If target is not reached within 5 completed candles after entry, exit at the next candle open.
- If stop and target are both touched in the same candle, assume stop first.
- No averaging down, pyramiding, or simultaneous opposite position in the same symbol.
- One open position per symbol. No capital sizing or portfolio allocation calculations.

## H1/session adaptation

The intended production mode is session trading, but the current historical H1 snapshot is only about 30 calendar days. It is not sufficient for four independent historical folds. Therefore this D1 definition is a research hypothesis only; it must not be described as a validated session strategy or used to emit session signals. A later H1 implementation must preserve the same failed-breakout logic on native completed H1 candles and must be evaluated on adequate H1 history before approval.

## Evaluation protocol

- Use the fixed 44-symbol universe and Finam-native data only.
- Development cutoff: 2026-11-19 inclusive. Holdout begins 2026-11-20 and is excluded.
- Preserve the four previously fixed chronological folds; do not change boundaries to improve results.
- LONG and SHORT results must be reported separately.
- Report per-fold trade count, net return per trade, profit factor, gross/net results, and instrument concentration.
- Costs: baseline 0.10% fee + 0.05% slippage per side; repeat with doubled costs.
- Require every fold to be profitable. Do not relax this requirement or tune parameters after viewing fold results.
- A fold with fewer than 5 completed trades is INSUFFICIENT, not a pass.
- Do not pool LONG and SHORT to conceal a losing side.
- Do not optimize the 20-bar range, 1.5 volume multiplier, ATR buffer, or 5-bar time stop on these same folds.
- If any fold is negative, either side fails, data coverage is incomplete, or costs erase profitability, mark the hypothesis FAILED / INSUFFICIENT. Do not promote it.

## Data-quality and execution safeguards

- Validate candle chronology, duplicates, OHLC consistency, missing sessions, and volume availability before simulation.
- Use only completed candles; signals at close, entries at next open.
- Do not use broker/account/order endpoints.
- Do not change the production scanner, executor, schedules, secrets, Telegram routing, or live-mode settings.
- No live orders, no production signals, and no automatic strategy-registry promotion.

## Current conclusion

This is a falsifiable hypothesis, not a claim of profitability. It has not been backtested. Its H1/session variant cannot be validated with the currently documented 30-day H1 history. The next legitimate step is one reproducible D1 research run against the fixed four folds, with a strict pass/fail report and no parameter search.
