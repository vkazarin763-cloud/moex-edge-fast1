# MOEX EDGE — equities-only external strategy review
Date: 2026-11-23

## Scope

Current research phase is limited to the fixed MOEX 44-stock universe. Futures and options are intentionally excluded from discovery runs and implementation work for now. Their architecture notes are not deleted.

This report records source-code review, not MOEX performance. No MOEX candles were loaded, no backtest was run, and no scanner eligibility is granted.

## Candidate 1 — Jason IE multi-indicator composite

- Repository: https://github.com/jason-ie/trading-strategy
- Reviewed immutable tree commit: `a255cd7ffe9b06fa36ca9ff0d59c89111d4c345d`
- Notebook blob: `c2d9c1ebc1d398ae8a526fac78aeb473df57a733`
- Source: `trading.ipynb` (18 cells)
- Universe: PLTR, TSLA, HOOD; SPY benchmark; daily bars.
- Source code obtains adjusted close plus raw high/low/open from Alpha Vantage.

### Rules recovered from notebook

1. Johnson-SU MLE is fitted to estimation-window daily log returns. A return below fitted 5th percentile emits +1; above 95th percentile emits -1.
2. Wilder RSI(14): +1 above 70 and -1 below 30 (momentum interpretation).
3. Ichimoku: bullish only when Tenkan > Kijun, current close above lag-safe cloud top, cloud A > B, and close above close 26 bars earlier; bearish conditions are symmetric.
4. ATR(14) activity signal: +1/-1 only when true range exceeds ATR, with direction from close-to-close move.
5. Composite score is MR + RSI + Ichimoku. Long if score >= 1. Short if score <= -1 and ATR activity signal is non-zero.
6. Signal at close of day i is followed by the next day's close-to-close log return, which corresponds to close(i) to close(i+1) if the adjusted-close series is internally consistent.

### Material gaps / defects to resolve before any port

- No deterministic exit, stop, target, or maximum holding rule is specified: each signal is a one-session exposure, not a complete multi-day trade lifecycle.
- The notebook combines adjusted close with unadjusted OHLC highs/lows for ATR and Ichimoku. Splits/dividends can therefore create inconsistent indicator inputs.
- No commission, spread, slippage, liquidity, or execution-cost model is applied to the reported result.
- The reported 385 trades have mean trade return 0.2794% and t-test p-value 0.1702 in the notebook output; this is not statistically significant at conventional levels. This is a source-reported calculation, not independently reproduced.
- Portfolio aggregation averages only the trades active on a date; this is a simplified allocation convention and needs a capital/exposure audit.
- Source universe is three US high-beta names. Transfer to the MOEX 44 is unproven.
- Source-reported rolling walk-forward outcomes are not evidence of MOEX edge.

**Disposition:** `INCOMPLETE`. Keep as a research hypothesis only. Do not implement in the signal scanner until exit/execution rules and consistent OHLC adjustment are resolved.

## Candidate 2 — Turtle System 1-style Donchian breakout

- Repository: https://github.com/bmonagan/backtester
- Reviewed immutable commit: `ba5156ec58f8d240af7b09b476fa8493171228d3`
- License: MIT (repository metadata and LICENSE file).
- Code: `src/backtester/strategy.py`, `TurtleTradingStrategy` / `DonchianBreakoutStrategy`.
- Unit test: `tests/test_turtle_strategy.py`.
- Market scope in implementation: long-only daily bars, generic symbols.

### Exact implemented rules

1. Entry period defaults to 20 bars; exit period defaults to 10 bars.
2. At each completed bar, calculate the highest high of the prior 20 bars, excluding the current bar.
3. If flat and current close is above that prior 20-bar high, emit a buy order.
4. While long, calculate the lowest low of the prior 10 bars, excluding the current bar.
5. If current close is below that prior 10-bar low, emit a sell order.
6. The engine queues orders from the signal bar and fills market orders at the next bar open.

### Important limits

- The implementation explicitly states it is only the channel-breakout signal, not the full original Turtle system.
- It does not include original N-based volatility risk sizing, pyramiding, protective stops, or the original breakout filter.
- The repository engine supports configurable spread/slippage/impact/commission, but the README's AAPL sample table is explicitly reported with zero costs. No cost-calibrated MOEX result exists.
- The code is a reusable implementation reference, not proof of profitability.

**Disposition:** `SOURCE_REVIEWED`; eligible for a controlled MOEX research test after data and execution checks. It is not scanner-eligible.

## Research queue — next actions

1. Use the MOEX 44 daily/weekly data branch already available in the project; verify OHLC consistency, splits/dividends, gaps, trading sessions, duplicate timestamps, and liquidity.
2. Implement a minimal, isolated Donchian 20/10 research adapter with signal-at-close / next-open execution. Do not copy the external backtester wholesale.
3. Test long-only first, with realistic MOEX commissions, spread and slippage sensitivity; compare with buy-and-hold and a simple benchmark.
4. Use chronological train/validation/untouched holdout and walk-forward folds. Freeze parameters before the final holdout.
5. Run parameter sensitivity around the published 20/10 values; do not optimize on the holdout.
6. Keep Jason IE candidate marked incomplete until the missing exit/execution specification and adjusted-OHLC inconsistency are resolved.

## Safety boundary

This document does not authorize live trading, broker connections, orders, position sizing, or promotion of either candidate. Research output remains isolated from the active scanner until independent validation passes.
