# Weekly Strategy Research — verified findings

**Snapshot:** 2026-11-28  
**Data source:** Finam weekly candles, account permission checked read-only  
**Universe:** 44 MOEX equities + 19 funds; 63 instruments total  
**Research only:** no orders, no portfolio sizing, no live execution

## 1. Data validation

The corrected weekly-history request stays within Finam's documented 1,825-day limit and allows only the bounded preceding weekly candle at the API boundary, which is removed before backtesting.

| Status | Count |
|---|---:|
| Qualified (>=200 validated weekly bars) | 56 |
| Insufficient history | 7 |
| API/data errors | 0 |

Qualified set: 41 equities and 15 funds. The seven excluded instruments are DOMRF (54 bars), SVCB (155), UGLD (157), AMNR (150), AMNY (127), BCSD (123), SBCB (167). The latest validated weekly candle is 2026-11-23. The 56 qualified instruments produced 840 metric rows (5 strategies x 3 illustrative one-way cost assumptions x 56 instruments).

## 2. Out-of-sample method

The five candidate rules were fixed before this holdout comparison: buy-and-hold, 20-week SMA trend, 13-week momentum, 4-week mean reversion, and 13-week breakout.

- Historical bars before 2025-01-06 are used only to warm up indicators.
- Holdout returns are measured from 2025-01-06 through 2026-11-23.
- A signal calculated at a weekly close is applied to the next weekly close-to-close return; no same-bar look-ahead.
- Turnover costs are charged on position changes at 0.10%, 0.25%, and 0.50% one-way. These are stress assumptions, not confirmed Finam tariffs or slippage.
- Summary uses the median CAGR across instruments, the count with positive CAGR, and median maximum drawdown. It is not a pooled portfolio backtest.

## 3. Holdout results — all 56 instruments

| Strategy | Median CAGR @0.10% | Positive instruments | Median CAGR @0.25% | Positive instruments | Median CAGR @0.50% | Positive instruments |
|---|---:|---:|---:|---:|---:|---:|
| Buy & hold | -8.81% | 19/56 | -8.81% | 19/56 | -8.81% | 19/56 |
| 20-week SMA trend | -4.28% | 18/56 | -5.01% | 18/56 | -6.25% | 17/56 |
| 13-week momentum | -4.72% | 18/56 | -5.29% | 18/56 | -6.70% | 16/56 |
| 4-week mean reversion | -8.74% | 15/56 | -10.30% | 8/56 | -12.94% | 5/56 |
| 13-week breakout | **+1.27%** | **30/56** | -0.09% | 28/56 | -1.86% | 23/56 |

The 13-week breakout has the best aggregate holdout profile, but its median return becomes approximately flat at 0.25% one-way cost and negative at 0.50%. This does not establish a robust all-asset edge.

## 4. Asset-class split

At 0.25% one-way cost:

| Asset class / strategy | Median CAGR | Positive instruments | Median max drawdown |
|---|---:|---:|---:|
| Equities — buy & hold | -10.93% | 8/41 | -48.96% |
| Equities — 13-week breakout | -2.41% | 14/41 | -12.33% |
| Funds — buy & hold | +6.68% | 11/15 | -25.11% |
| Funds — 13-week breakout | **+7.61%** | **14/15** | **-5.24%** |

13-week breakout fund sensitivity:

| One-way cost | Median CAGR | Positive funds | Median max drawdown |
|---|---:|---:|---:|
| 0.10% | +9.82% | 15/15 | -3.72% |
| 0.25% | +7.61% | 14/15 | -5.24% |
| 0.50% | +4.04% | 12/15 | -6.14% |

The promising result is concentrated in the fund group. The same breakout rule is not profitable on the median equity in this holdout. Funds are a small sample (15), and the period may be regime-specific.

## 5. Decision

**No strategy is approved for live trading or production signals.**

Research priority for the next stage:
1. Treat 13-week breakout on funds as a *candidate only*.
2. Run additional rolling/anchored walk-forward folds and report every fold, not only the selected holdout.
3. Validate instrument-level results, turnover, gaps, spread and realistic instrument-specific costs; avoid treating a common illustrative fee as actual execution cost.
4. Test parameter stability around 13 weeks without selecting parameters on the final holdout.
5. Keep equities as a separate research problem; do not generalize the fund result to shares.
6. Build dedicated coupon/maturity models for bonds and expiry/multiplier/roll models for futures; options require historical bid/ask and expiry/strike-aware payoff modelling. Do not compare these asset classes using the simple weekly equity/fund model.

## 6. Reproducibility and artifacts

- Finam weekly batch workflow: [run 46157777532](https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/46157777532)
- Corrected boundary implementation: [commit 43631d9](https://github.com/vkazarin763-cloud/moex-edge-fast1/commit/43631d95ff5ea0a0d92d8cc91d00228f18a12a6e)
- Artifact: `weekly-strategy-research` (JSON contains the 56 validated weekly series; CSV contains all 840 metric rows; artifact retention 90 days).

The holdout summary above was calculated from the downloaded artifact with the strategy rules and lagged-return convention described in section 2. This report is a research record, not investment advice or a promise of future performance.
