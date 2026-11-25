# Confirmed trend reversal test — 2026-11-21 snapshot

## Hypothesis tested

A deliberately simple, fixed H1 trend-following reversal rule:

- Calculate EMA20 and EMA50 using completed H1 closes.
- A bullish regime requires close > EMA50 and EMA20 > EMA50.
- A bearish regime requires close < EMA50 and EMA20 < EMA50.
- Confirm a new regime only after two consecutive completed H1 bars meet the same bullish/bearish condition.
- Keep the previous position while a new regime is not confirmed.
- Position decided at the close of bar t is applied only to the return from close(t) to close(t+1). No same-bar execution or look-ahead.

This is a trend-state confirmation test, not a fitted model and not an options backtest.

## Data and sample

- Input: archived Finam H1 data from GitHub Actions run `44889538524`, artifact ID `14701243872`.
- Snapshot: `2026-11-21T09:25:51.184499+00:00`.
- 44 MOEX symbols; all 18,648 completed H1 bars in archive.
- Weekends excluded; evaluation uses the same five weekday dates as the earlier quick screen: 2026-11-13, 2026-11-16, 2026-11-17, 2026-11-18, 2026-11-19.
- Only next-bar returns whose current and next timestamps both fall inside this evaluation window are included.
- 3,696 ticker-hour return observations across 44 symbols.
- EMA values are warmed up on earlier available weekday bars before the evaluation window.
- Frozen D1 prospective holdout from 2026-11-20 onward is not used.

## Results

- Gross mean signed return: **-0.009 bps per ticker-hour** (effectively flat, slightly negative).
- Positive ticker-hour observations: **50.43%**.
- LONG exposure observations: 1,969.
- SHORT exposure observations: 1,727.
- Position entries/reversals during evaluation: 128 (initial entry counted once per symbol).
- Mean underlying market return over these intervals: **-4.162 bps**; therefore always-SHORT gross benchmark: **+4.162 bps** per ticker-hour.

### Illustrative transaction-cost sensitivity

Assumption: 15 bps per one-way side. Initial entry costs 15 bps; a reversal costs 30 bps to close and reopen; no cost charged while holding.

- Mean cost allocated per ticker-hour: 0.860 bps.
- Net mean signed return: **-0.870 bps per ticker-hour**.

This is a stated sensitivity assumption, not a verified per-instrument execution-cost schedule. No borrow, funding, taxes, market impact, or options spreads were modeled.

## Decision

**No demonstrated edge.** The EMA20/EMA50 regime with two-bar confirmation avoided the extreme turnover of flipping on every candle, but it did not generate positive gross performance and lagged the always-SHORT benchmark on this bearish five-session sample. Under the illustrative cost assumption it was negative.

Do not deploy this rule, send it to Telegram, or use it to select options. A longer test may be justified only if a separately pre-registered hypothesis is available. Do not tune EMA periods or confirmation thresholds on these same five sessions and report the result as unbiased.

## Scope

Read-only historical research. No production code, scheduled workflows, Telegram, Finam executor, broker integration, or real orders were changed.
