# MOEX EDGE Indicator Optimizer V1

Status: research-only implementation; no production scanner or executor changes.

## Scope
- Repository: `vkazarin763-cloud/moex-edge-fast1`
- Branch: `research/indicator-optimizer-v1`
- Instruments: the configured 44 TQBR shares in `moex_edge_fast_33.py`.
- Native MOEX ISS candle intervals: 10 minutes and 60 minutes. ISS does not provide a native 15-minute interval; do not label 10-minute candles as M15. If M15 is later required, construct it only from complete 1-minute bars and validate coverage/session boundaries.
- Directions: LONG and SHORT evaluated independently.
- No broker API, order submission, Telegram, or production file edits. The only workflow added is a manual research run on this branch.

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
1. Fetch and validate actual MOEX ISS candles; record source, timestamps, coverage, duplicates, invalid OHLC, incomplete final candles, and excluded out-of-session bars by ticker/timeframe. Raw data is cached locally between runs.
2. Use only completed candles. A signal formed on candle close may enter no earlier than the next available candle open. Each trade must also exit within its chronological partition; trades crossing train/validation/test boundaries are excluded.
3. Evaluate 10-minute and 60-minute data separately; never mix timeframe results.
4. Evaluate LONG and SHORT separately, per ticker first, then report pooled test results by timeframe, strategy family, parameter set, and direction. Do not silently pool incompatible instruments.
5. Use chronological train/validation/test partitions and four sequential training-stability blocks inside the training segment (20%–60% of the timeline). Validation (60%–80%) selects candidates; final test (80%–100%) remains untouched. The final test segment remains untouched during parameter selection.
6. Include commission and a configurable conservative spread/slippage model; report gross and net returns separately and run cost sensitivity. OHLC candles alone do not prove historical bid/ask spread.
7. Report trade count, win rate, mean/median gross and net return, profit factor, and max drawdown per ticker plus pooled test statistics. No portfolio capital or position-size calculations in user-facing reports.
8. The validation shortlist requires at least 10 validation trades, positive validation mean net return, at least 3 of 4 walk-forward blocks with 5+ trades, and positive mean net return across active blocks. This is a screen, not a guarantee. Do not select solely by win rate or the single best historical result.
9. Compare optimized settings against the unchanged default settings on exactly the same timestamps and execution assumptions.

## Promotion rule
Research output is a report/config candidate only. No automatic parameter update to FAST 4.0. Any production adoption requires a separate explicit review and approval after out-of-sample evidence.


## Implemented execution model
- The current version tests each indicator family independently (not all combinations together), using a fixed 3-bar holding horizon to isolate indicator parameter quality from exit-parameter optimization.
- Entry is next candle open; exit is the close after the configured number of bars. One trade per ticker/family/direction may be open at a time; overlapping signals are skipped.
- The default modeled round-trip fee is 0.26% and round-trip slippage sensitivity is 0.10%. These are explicit assumptions, not verified current Finam tariffs or measured historical spreads; both are configurable.
- Default date range begins 2025-01-01. CSV cache avoids re-downloading unchanged ticker/timeframe/date ranges. --refresh forces a reload.
- Results include data_quality.csv, candidate_results.json, validation_shortlist.json, pooled_test_results.json, and summary.json.
- Run unit tests from this directory with python -m unittest -v.
- Manual GitHub Actions run: Actions → Indicator optimizer research → Run workflow. Outputs are uploaded as a 30-day artifact.

## Current limits
- The initial engine evaluates indicator families separately; it does not yet search multi-indicator ensembles or optimize exit rules.
- The final test segment is reported but never used to select the validation shortlist. Pooled results are grouped by exact parameter set; inspect ticker-level dispersion before interpreting them. Training-stability fold metrics are also stored per ticker/candidate and do not use validation or final-test candles.
- The current model uses fixed-horizon exits and candle OHLC, not historical bid/ask quotes. Treat results as a research screen, not executable performance.
- Only weekday main equity session (09:00–19:00 Moscow time after 14-Sep-2026) is included. Morning/evening additional sessions and weekend additional sessions are excluded and counted in data-quality output.
- Verify current fee schedule and model spread/slippage conservatively. Never present modeled costs as exact historical costs.
