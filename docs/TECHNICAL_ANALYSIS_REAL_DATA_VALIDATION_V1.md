# MOEX EDGE — real-data technical-analysis validation v1

## Result

The isolated Pandas TA Classic adapter completed **132/132 analyses** for the 44-stock universe on D1, H1 and W1. The run completed with zero adapter/data errors.

- GitHub Actions run: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45316185450
- Report artifact: `moex-ta-frozen-44-d1-h1-w1-report` (summary.csv and features.json; retained for 30 days)
- Frozen source-data run: `44861047844`
- Frozen source artifact: `14690518588`
- Source artifact SHA-256: `6a9ee767f37bec1f9fa9d40d0868ccc8f36b2271dd5ef4a1715f83e4a51af137`
- Source validation: `PASS`, 44 symbols, zero reported issues
- Source data generated: `2026-11-21T03:25:33Z`

## Holdout protection

The analysis excludes every bar with a date **on or after 2026-11-20**. The run excluded 792 bars across the selected timeframes. The latest analyzed H1 bar was `2026-11-19T20:00:00+00:00`; D1 ended on 2026-11-19 and W1 on 2026-11-09. The runner verifies the two frozen JSON file hashes before processing and checks the cutoff again for every symbol/timeframe.

## Coverage

| Timeframe | Symbols analyzed | Bars per symbol (min–max) | Level pivot lookback |
|---|---:|---:|---:|
| D1 | 44/44 | 253–1,251 | 250 bars |
| H1 | 44/44 | 407–410 | 240 bars |
| W1 | 44/44 | 52–257 | 104 bars |

All 132 rows have EMA20, EMA50, RSI14, ATR14, ADX14 and relative-volume values. EMA200 is unavailable for 8 W1 rows because those symbols have fewer than 200 weekly bars; this is expected warm-up behavior, not a calculation failure.

## Descriptive output observed

- 47 of 132 latest-bar analyses contained at least one candlestick-pattern detection (57 detections in total).
- Pattern detections: Doji 20, Hammer 13, Inside 11, Engulfing 11, Shooting Star 2. No Morning Star or Evening Star detections appeared in the latest bars.
- Channel classifications across the 132 analyses: UP 45, DOWN 82, SIDEWAYS 4, insufficient history 1.
- Support/resistance zones are now restricted to recent completed-bar windows and the nearest 8 zones of each type (maximum 16 zones per analysis), rather than returning every historical price cluster.

These counts describe the adapter's output only. They are **not** trading signals, backtest results, evidence of predictive power, or profitability estimates.

## Limitations and next validation

1. Candlestick pattern detections are library labels; they have not been tested for forward returns or statistical significance on MOEX.
2. The OLS channel is a descriptive fit, not a guaranteed price boundary. Channel thresholds have not been optimized.
3. The nearest-zone cap improves readability but does not prove that the zones are actionable. Weekly levels can still be distant from the last close; use the reported distance percentage when reviewing them.
4. The next meaningful research step is a chronological, non-holdout comparison of the detected features against forward outcomes, with costs and a separate holdout protocol. Do not turn these features into live LONG/SHORT signals until that validation is complete.

## Safety boundary

This adapter and its report remain isolated in the development repository. The active scanner is unchanged. No broker connection, orders, capital allocation, position sizing, or LONG/SHORT recommendations are involved.
