# MOEX EDGE Indicator Optimizer V1

Status: research-only design; no production scanner or executor changes.

## Scope
- Repository: `vkazarin763-cloud/moex-edge-fast1`
- Branch: `research/indicator-optimizer-v1`
- Instruments: the configured 44 TQBR shares in `moex_edge_fast_33.py`.
- Native MOEX ISS candle intervals: 10 minutes and 60 minutes. ISS does not provide a native 15-minute interval; do not label 10-minute candles as M15. If M15 is later required, construct it only from complete 1-minute bars and validate coverage/session boundaries.
- Directions: LONG and SHORT evaluated independently.
- No broker API, order submission, live workflow dispatch, Telegram, or production file edits.

## Existing baseline discovered
The current FAST 4.0 scanner hardcodes:
- EMA 20/50/200
- RSI 14 with 30/70 crossings
- MACD 12/26/9
- ADX/DI 14 with ADX threshold 20
- Donchian 20/55
- Bollinger 20 with 2 standard deviations
- Stochastic 14/3 with 20/80 zones
- ATR 14; Keltner EMA20 +/- 2 ATR
It primarily creates signals on D1 and uses H1 EMA20 as a confirmation. Existing priority weights are manually assigned and the threshold is 7. This is not parameter optimization.

## Search space (initial bounded grid)
- EMA: fast [8, 10, 12, 15, 20], slow [30, 40, 50, 60, 80], fast < slow.
- RSI: period [7, 9, 14, 21]; symmetric threshold pairs [25/75, 30/70, 35/65].
- MACD: [8/21/5, 12/26/9, 10/30/9, 5/35/5].
- ADX/DI: period [10, 14, 20], strength threshold [18, 20, 25, 30].
- Bollinger: period [14, 20, 30], deviation [1.8, 2.0, 2.2].
- Donchian: lookback [10, 20, 30, 55].
- ATR/Keltner: ATR period [10, 14, 20], multiplier [1.5, 2.0, 2.5].
- Stochastic: [9/3/3, 14/3/3, 21/5/5].
The grid is a candidate search space, not a claim that any setting is best.

## Validation protocol
1. Fetch and validate actual MOEX ISS candles; record source, timestamps, coverage, missing intervals, duplicates, invalid OHLC, and session filtering by ticker/timeframe.
2. Use only completed candles. A signal formed on candle close may enter no earlier than the next available candle open.
3. Evaluate 10-minute and 60-minute data separately; never mix timeframe results.
4. Evaluate LONG and SHORT separately, per ticker first, then report pooled results. Do not silently pool incompatible instruments.
5. Use chronological train/validation/test partitions and walk-forward checks. The final test segment remains untouched during parameter selection.
6. Include commission and a configurable conservative spread/slippage model; report gross and net returns separately and run cost sensitivity. OHLC candles alone do not prove historical bid/ask spread.
7. Report trade count, win rate, mean/median net return, profit factor, max drawdown, exposure/time-in-market, and stability across folds/tickers. No portfolio capital or position-size calculations in user-facing reports.
8. Reject settings with too few trades, unstable fold performance, or negative net expectancy. Do not select solely by win rate or the single best historical result.
9. Compare optimized settings against the unchanged default settings on exactly the same timestamps and execution assumptions.

## Promotion rule
Research output is a report/config candidate only. No automatic parameter update to FAST 4.0. Any production adoption requires a separate explicit review and approval after out-of-sample evidence.

## Known caveats to resolve before first run
- Confirm current TQBR session windows and filter official sessions correctly; do not reuse broad unverified time filters.
- Confirm MOEX ISS candle availability per ticker/timeframe via candle borders.
- Validate OHLC-based stop/target ordering when both levels are touched within one candle; use conservative adverse ordering or finer data.
- Verify fee schedule and model spread/slippage conservatively. Never present modeled costs as exact historical costs.
