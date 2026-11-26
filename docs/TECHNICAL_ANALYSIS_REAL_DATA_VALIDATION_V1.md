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


## Chronological feature event study — version 2

A separate exploratory event study was run on the same immutable source data after adding segmentation around five extreme price-scale discontinuities (GMKN, PLZL, T, TRNFP, VTBR). No forward return crosses one of these discontinuities.

- Workflow run: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45317485746
- Event-study artifact: `moex-ta-chronological-event-study` (events.csv, summary.csv, report.json; retained 30 days)
- 132 symbol/timeframe series processed, 137 continuous segments, zero processing errors.
- 781,996 event observations across D1/H1/W1 and 1/3/5/10-bar horizons.
- Development period: before 2026-07-01. Validation period: 2026-07-01 through 2026-11-19.
- Signal observed at completed close; entry at next bar open; exit at close after the selected horizon.
- Assumed round-trip cost: 0.16% (0.08% per side).
- All 792 bars dated 2026-11-20 onward were excluded.

### Validation-period aggregate results

Event-weighted descriptive averages; directional returns include the assumed round-trip cost. These aggregate different labels/horizons and are not a portfolio return.

| Feature | Directional observations | Mean net event return | Matched baseline | Excess vs baseline | Event win rate |
|---|---:|---:|---:|---:|---:|
| Candlestick patterns | 18,565 | -0.1308% | -0.1537% | +0.0229 pp | 35.54% |
| EMA stack | 37,358 | -0.5060% | -0.3209% | -0.1851 pp | 36.74% |
| OLS channel | 74,952 | -0.3130% | -0.2354% | -0.0776 pp | 36.21% |
| Confirmed pivot proximity | 69,413 | -0.1337% | -0.1504% | +0.0167 pp | 37.19% |

Neutral Doji/Inside patterns and sideways-channel observations are measured by absolute price movement, not directional return, and are intentionally excluded from the table above.

### Interpretation

1. No tested feature demonstrated a positive average net directional return in the validation period. The slightly positive relative excess for candle patterns and pivot proximity does not change their negative mean net returns and low event win rates.
2. EMA-stack and OLS-channel directions underperformed their matched baselines in the validation period.
3. The most encouraging individual subsets (e.g. Morning Star and Shooting Star) are sparse: most timeframe/horizon groups are below 30 observations. They are hypotheses for further testing, not usable signals.
4. Near-resistance SHORT observations were less negative than the matched baseline on average, but their mean net return remained negative. Near-support LONG observations underperformed their baseline.
5. The validation period's aggregate event win rates (about 35–37% for directional feature families) do not support activation of these features as standalone trading entries.

This is a simple, overlapping event study. It does not correct for multiple testing, dependence between repeated/overlapping observations, volatility regimes, or all market microstructure effects. The matched baseline is the same symbol/timeframe/period/horizon's unconditional directional return average, not a matched control portfolio. No statistical significance, risk-adjusted edge, portfolio performance, or profitability is established.

**Decision:** keep the adapter descriptive and disabled as a signal source. The next useful research step is a narrower, pre-registered set of hypotheses with non-overlapping events, per-symbol robustness, regime controls, and costs/slippage sensitivity. Do not tune on or inspect the sealed period beginning 2026-11-20.


## Non-overlapping robustness and cost sensitivity — version 3

A second pass was added to reduce repeated/overlapping event observations and to test whether apparent effects are spread across symbols.

- Final workflow run: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45318840663
- Final report artifact: `moex-ta-chronological-event-study` (includes `nonoverlap_summary.csv`, `nonoverlap_by_label.csv`, `cost_sensitivity.csv`, `per_symbol_sign_robustness.csv`, and the original event files; 30-day retention).
- Input: 781,996 event rows.
- 97,822 same-bar conflicting-direction rows excluded; 14,078 same-bar same-direction duplicate labels collapsed.
- Family-level chronological non-overlap selection retained 321,270 events (47.94% of the cleaned rows). Label-level selection retained 346,610 events; separate labels can still overlap one another.
- Results are first averaged within each symbol, then symbols are equally weighted.
- Cost sensitivity uses round-trip assumptions of 0.16%, 0.32%, 0.64%, and 1.00%. The baseline is adjusted by the same cost.

### Multiple-testing and cross-symbol robustness

There are 140 directional label/timeframe/horizon groups in the validation period. For each group, a one-sided sign test checks whether more symbols had positive mean event returns or positive mean excess versus their own matched baseline. Benjamini-Hochberg adjustment is applied across all 140 groups.

- Best adjusted q-value for positive net-return signs: **0.0299**.
- Best adjusted q-value for positive excess-versus-baseline signs: **0.0882**.
- Therefore **no tested group clears the 5% false-discovery threshold for consistent positive excess over its baseline**.
- The lowest q-value for positive net return belongs to weekly Hammer/LONG at a 5-bar horizon (22 symbols, 26 events). Its positive excess does not survive multiple-testing adjustment (q = 0.1013); this is a small, exploratory subset, not a validated trading edge.

The sign test treats symbols as independent for this diagnostic, although MOEX shares are correlated. It is not a substitute for a block bootstrap or a time-series model.

### Cost sensitivity example

The broad D1 candlestick-pattern family at a 5-bar horizon had 440 non-overlapping observations across 44 symbols:

| Assumed round-trip cost | Equal-symbol mean net return | Equal-symbol win rate |
|---|---:|---:|
| 0.16% | +0.5336% | 51.11% |
| 0.32% | +0.3736% | 49.55% |
| 0.64% | +0.0536% | 47.02% |
| 1.00% | -0.3064% | 44.07% |

This is a post-hoc aggregate over several candle labels. It is not a pre-registered signal, and the positive mean does not establish a repeatable edge. The label-level sign tests do not establish significant excess versus baseline after multiple-testing correction.

**Decision remains unchanged:** keep technical-analysis features descriptive only. Do not connect them to live LONG/SHORT signals. A future candidate must be specified before another test, validated over a longer chronological sample, compared with a matched baseline, and pass symbol-level robustness and realistic spread/fee/slippage checks. The sealed period from 2026-11-20 onward remains untouched.
