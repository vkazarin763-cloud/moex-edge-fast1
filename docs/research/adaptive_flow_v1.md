# MOEX EDGE Adaptive Flow v1 — MOEX ISS research specification

Status: FIXED RESEARCH HYPOTHESIS; NOT BACKTESTED; NOT APPROVED FOR SIGNALS OR TRADING.

## Data source

- Use public MOEX ISS per-security TQBR total-session daily history (history endpoint, `TRADEDATE`), via the existing `research_agent/moex_iss.py::fetch_history_records` loader.
- Do not use Finam candles for this experiment; do not blend sources.
- Development data may begin 2023-11-20. The frozen evaluation window remains 2025-11-20 through 2026-11-19 inclusive, split into the four already-fixed folds below. Earlier eligible MOEX ISS bars are warm-up/context only.
- Holdout begins 2026-11-20 and must not be fetched into the model input, indicators, signals, trade simulation, or selection.
- Use the fixed 44-symbol universe. Validate source coverage, price basis/corporate actions, missing/duplicate dates, zero-trade rows, OHLC consistency and volume availability. Fail closed for incomplete or incompatible data; do not silently substitute Finam.
- Label every report explicitly as MOEX ISS TQBR D1. This is not Finam data and does not validate an H1/session strategy.

## Fixed strategy rules

A symmetric failed-range-breakout (liquidity-sweep) hypothesis. All calculations use completed native MOEX ISS TQBR D1 trading-day bars.

For each symbol and completed bar t:
- Prior range uses the 20 completed bars immediately before t: prior_high=max(high[t-20:t]), prior_low=min(low[t-20:t]).
- LONG setup: low[t] < prior_low AND close[t] > prior_low.
- SHORT setup: high[t] > prior_high AND close[t] < prior_high.
- Relative-volume confirmation: volume[t] >= 1.5 * median(volume[t-20:t]). If volume is missing or invalid, no signal.
- Evaluate only after bar t closes. Enter at the next eligible D1 trading-day open. Never fill on the signal bar.

## Risk and exit

- LONG invalidation: signal-bar low minus 0.10 * ATR(14) measured at signal close.
- SHORT invalidation: signal-bar high plus 0.10 * ATR(14) measured at signal close.
- If next open has crossed the invalidation level, skip entry.
- Initial target: midpoint of the prior 20-bar range.
- If target is not reached within five completed bars after entry, exit at the next eligible bar open.
- If stop and target are both touched in one bar, assume stop first.
- One open position per symbol; no pyramiding, averaging down or opposite simultaneous position.
- No capital sizing or portfolio allocation calculations.

## Frozen walk-forward evaluation

Use the four pre-defined non-overlapping evaluation folds; bars before each fold are warm-up only:
1. 2025-11-20 to 2026-02-26
2. 2026-02-26 to 2026-05-27
3. 2026-05-27 to 2026-08-24
4. 2026-08-24 to 2026-11-20 (end exclusive)

For each fold:
- Signals must occur inside the fold. Entry and exit must be simulated using eligible data within that fold; terminal open trades are excluded from realized trade statistics.
- Report LONG and SHORT separately; neither side may conceal losses on the other.
- Report trade count, net mean return per trade, profit factor, gross/net results, per-symbol contribution and concentration.
- Costs: 0.10% fee + 0.05% slippage per side; repeat with doubled costs.
- Every fold must be profitable. A fold with fewer than five completed trades is INSUFFICIENT, not a pass.
- Do not tune the 20-bar range, 1.5 volume multiplier, ATR buffer or five-bar time stop on these same folds. Do not relax thresholds after seeing results.
- If a fold is negative, a direction fails, costs erase profitability, source coverage is incomplete, or corporate-action price basis is unresolved, mark FAILED / INSUFFICIENT. No promotion.

## Safety and scope

- Read-only public MOEX ISS market data only. No broker/account/order/position endpoints.
- Do not modify production scanner, executor, schedules, secrets, Telegram routing or live-mode settings.
- No real orders, production signals, or automatic registry promotion.
- A successful D1 result is only a D1 research result. It does not establish H1/session performance; that requires its own adequate native H1 dataset and separate validation.

## Implementation note

The repository already contains `research_agent/moex_iss.py::fetch_history_records` for TQBR daily history and `research_agent/candle_level_research.py` for a separate three-year MOEX ISS research pipeline. The latter currently tests other candle/level hypotheses with a Chandelier exit; it is NOT the Adaptive Flow runner. A dedicated Adaptive Flow backtest implementation and report are still required before any performance claim can be made.
