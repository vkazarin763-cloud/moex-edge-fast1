# Preliminary H1 direction pilot — 2026-11-21 snapshot

Status: **REJECTED AS A PROMISING EDGE IN THIS QUICK SCREEN**. This is a small exploratory result, not a final strategy evaluation.

## Input

- GitHub Actions collector run: `44889538524`.
- Artifact: `moex-edge-multi-timeframe-candles`, ID `14701243872`.
- Snapshot generated: `2026-11-21T09:25:51.184499+00:00`.
- Universe: 44 symbols; H1 source: Finam.
- H1 data structurally validated in the collector report. The archive was independently inspected for this pilot.
- Raw H1 rows on weekend dates were excluded from this weekday-only comparison and are not relabelled as regular MOEX-session candles.
- Training: 10,779 labeled observations, dates before 2026-11-13.
- Evaluation: 3,696 labeled observations across 44 symbols, on 2026-11-13 and 2026-11-16 through 2026-11-19.
- Any target whose next candle was on/after 2026-11-20 was excluded. The frozen prospective holdout was not used.
- The target is the next available weekday H1 close direction versus the current weekday H1 close. This is a one-bar classification target, not an options return.

## Results

| Method | Accuracy | Balanced accuracy | Mean signed next-bar return before costs |
|---|---:|---:|---:|
| Always SHORT (training-set majority baseline) | 55.30% | 50.00% | +4.162 bps |
| Previous-bar direction persistence | 45.29% | 44.75% | -2.497 bps |
| Fixed EMA/momentum rule | 50.81% | 47.68% | +1.150 bps |
| Logistic regression (fixed small feature set) | 52.44% | 52.63% | +0.224 bps |

The evaluation period itself was bearish: 44.70% of labels were UP. Therefore the always-SHORT baseline obtained 55.30% raw accuracy without forecasting skill. None of the tested methods beat that accuracy baseline. The logistic model's balanced accuracy was only 52.63%, and its mean signed return was negligible before costs.

## Cost sensitivity

At an illustrative 30 bps round-trip cost assumption, mean signed returns become:
- Always SHORT: -25.838 bps
- Persistence: -32.497 bps
- EMA/momentum: -28.850 bps
- Logistic regression: -29.776 bps

The 30 bps figure is a sensitivity assumption, not a verified H1 execution-cost estimate for every ticker. Even before costs, no tested model demonstrated a useful advantage over the simple directional baseline.

## Interpretation and limitations

1. **No demonstrated predictive edge.** The quick screen does not justify promoting any model or wiring it into Telegram.
2. The 3,696 rows are not 3,696 independent market observations: symbols and adjacent hourly bars are correlated. The five-session sample is especially short.
3. This test uses an archived snapshot through 2026-11-21, not current data. The result is useful for rejection, not for claiming stable performance.
4. The model is a pooled cross-sectional prototype with fixed features; no broad hyperparameter search was performed.
5. No options prices, implied volatility, bid/ask spreads, or option execution were tested.
6. Weekend Finam H1 bars were excluded from this weekday-only test; they remain source-specific technical observations.
7. This experiment is isolated from the frozen D1 cohort and its prospective holdout. Do not modify that cohort or infer anything about its eventual result from this pilot.

## Decision

Do **not** promote the tested H1 methods. Before spending more time, obtain a fresh H1 snapshot and run a pre-registered, slightly longer chronological test with a minimum viable set of hypotheses and realistic per-symbol costs. If a candidate still cannot beat the majority baseline and costs, stop this line of work rather than adding more indicators.
