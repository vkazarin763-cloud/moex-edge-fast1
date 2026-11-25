# Buyer/seller pressure proxy test — 2026-11-21 snapshot

## Purpose

Exploratory test of whether unusually strong volume-weighted candle pressure predicts the next H1 close direction. This is only an OHLCV proxy. It is **not true order flow**: the archive does not contain aggressor-side trade flags, trade-by-trade prints, or order-book depth.

## Hypothesis and fixed construction

For each completed H1 candle:

- Close Location Value (CLV) = (2 × close − high − low) / (high − low), bounded naturally by the candle range.
- Signed-volume proxy = volume × CLV.
- Pressure ratio = signed-volume proxy divided by the rolling 20-bar median absolute signed-volume proxy (minimum 10 observations).
- Relative volume = current volume divided by the rolling 20-bar median volume (minimum 10 observations).
- LONG when pressure ratio is at or above the training 75th percentile and relative volume is at or above the training 75th percentile.
- SHORT when pressure ratio is at or below the negative training 75th percentile and relative volume is at or above the training 75th percentile.
- Otherwise NO SIGNAL.
- Signal formed at close(t) is evaluated only against close(t+1); no same-bar execution.

Thresholds estimated only from observations before 2026-11-13:
- Relative-volume 75th percentile: 1.9119.
- Absolute pressure-ratio 75th percentile: 2.2596.

## Data and evaluation

- Source: Finam H1 OHLCV in GitHub Actions run 44889538524, artifact 14701243872.
- Snapshot generated 2026-11-21T09:25:51.184499+00:00.
- 44 MOEX symbols; 18,648 completed H1 bars in the archive.
- Evaluation dates: 2026-11-13 and 2026-11-16 through 2026-11-19.
- 3,696 eligible ticker-hour observations; targets whose next bar was on/after 2026-11-20 excluded.
- Weekend observations excluded from this weekday evaluation.
- This is the same short, bearish five-session quick-screen window used by the earlier H1 direction pilot; it is not an independent long-term validation.

## Results

- Signals: 744 / 3,696 observations (20.13% coverage).
- LONG: 351; SHORT: 393; NO SIGNAL: 2,952.
- Directional accuracy on signaled observations: 40.46%.
- Mean signed next-bar return on signaled observations, before costs: -7.28 bps.
- Mean signed contribution per all eligible observations, treating NO SIGNAL as flat: -1.47 bps.
- Always-SHORT benchmark on the same eligible observations: +3.72 bps per observation before costs (recomputed on the exact 3,696-row set used here).

## Decision

**Reject this pressure-continuation rule in this quick screen.** It underperformed the always-SHORT baseline and was negative before transaction costs. Do not wire it into the scanner or Telegram.

## Important limitations

1. CLV × volume is a candle-shape proxy, not buyer-initiated minus seller-initiated traded volume. A green candle does not prove aggressive buying; a red candle does not prove aggressive selling.
2. The five-session evaluation is very short and the ticker-hour observations are correlated.
3. No verified per-instrument fees, bid/ask spread, slippage, market impact, borrow, or financing costs were applied. Results are gross and already negative.
4. This archived snapshot is historical and cannot establish current market behavior.
5. A genuine order-flow test requires timestamped trades with aggressor-side classification (or a defensible quote/tick rule) and preferably order-book changes. Those data are not present in this archive.

## Next research decision

Do not keep changing thresholds on this same five-session test. If pursuing this direction, first obtain genuine trade/quote or order-book data with provenance and test a pre-registered imbalance/absorption hypothesis on a fresh chronological holdout. If such data are unavailable at acceptable cost, stop the order-flow line rather than relabel OHLCV indicators as order flow.

No production, live execution, Telegram, Finam executor, broker integration, or scheduled workflow was changed.
