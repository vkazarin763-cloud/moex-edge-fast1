# H1 volume-pressure proxy test — 2026-11-25

## Decision

**No predictive edge demonstrated. Do not promote this proxy.**

The available archive contains OHLCV candles only. It does not contain aggressor-side trade classification, bid/ask executions, order-book depth, or reliable buyer-initiated versus seller-initiated volume. Therefore this experiment tests candle-derived volume proxies, **not true order flow**.

## Data and evaluation

- Repository: `vkazarin763-cloud/moex-edge-fast1`
- Research branch: `research/h1-direction-forecast-v1`
- Source artifact: GitHub Actions run `44889538524`, artifact ID `14701243872`.
- Snapshot timestamp: `2026-11-21T09:25:51.184499+00:00`.
- Source: Finam H1 OHLCV, 44 MOEX symbols.
- Archive metadata: 18,648 completed H1 bars.
- Evaluation sessions: 2026-11-13 and 2026-11-16 through 2026-11-19.
- Weekends excluded. The frozen D1 prospective holdout from 2026-11-20 onward was not used.
- Exact common evaluation sample: 3,696 ticker-hour observations.
- Target: next eligible weekday H1 close versus current H1 close.
- Features use only the current and earlier completed bars. Position/signal is applied to the next H1 return.
- All methods use the same 3,696 observations except filtered variants, whose coverage is reported separately.

## Proxies tested

1. **Close-location volume pressure (3 bars):** for each candle, `CLV = (2*close - high - low)/(high-low)`; multiply CLV by volume, sum over the last three completed bars, divide by their total volume. Signal is the sign of this pressure.
2. **Candle-body volume pressure (3 bars):** multiply volume by the sign of `close-open`, sum over the last three bars, divide by total volume. Signal is the sign.
3. Two fixed filtered variants additionally require absolute pressure >= 0.15 (CLV) or >= 0.25 (body proxy), and current volume >= trailing median of the previous 20 bars. These thresholds are exploratory fixed cutoffs, not optimized.

Neither CLV nor candle-body sign identifies the actual aggressor. Both are rough OHLCV proxies.

## Results

| Method | Coverage | LONG / SHORT | Accuracy | Balanced accuracy | Mean signed next-H1 return |
|---|---:|---:|---:|---:|---:|
| Always SHORT baseline | 100% | 0 / 3,696 | 55.30% | 50.00% | +4.162 bps |
| 3-bar CLV × volume | 100% | 1,733 / 1,963 | 45.91% | 45.53% | -0.815 bps |
| 3-bar candle-body × volume | 100% | 1,639 / 2,057 | 49.16% | 48.55% | +1.395 bps |
| CLV proxy + pressure/volume filter | 32.39% | 502 / 695 | 42.44% | 41.81% | -2.235 bps |
| Body proxy + pressure/volume filter | 37.42% | 547 / 836 | 46.57% | 45.92% | +1.734 bps |

Mean signed return is measured in basis points per predicted next-H1 interval, before costs. For the filtered variants it is calculated only on emitted signals. The always-SHORT baseline is included on the full common sample.

### Illustrative cost sensitivity

Subtracting an illustrative 30 bps round-trip cost from each emitted hourly signal gives:
- 3-bar CLV × volume: -30.815 bps per signal.
- 3-bar candle-body × volume: -28.605 bps per signal.
- Filtered CLV proxy: -32.235 bps per signal.
- Filtered body proxy: -28.266 bps per signal.

The 30 bps is a sensitivity assumption, not a verified per-symbol execution cost. No spread, market impact, financing, borrow, or options costs were measured. These are next-H1 directional tests, not a complete position-management backtest.

## Interpretation

- Neither proxy beat the always-SHORT baseline on raw accuracy.
- Both filtered variants reduced coverage but did not improve predictive quality enough to justify that loss of coverage.
- The body-volume proxy had slightly positive gross mean signed return, but its accuracy and balanced accuracy remained below the baseline; this is not evidence of a robust edge.
- Observations across tickers and adjacent hours are correlated. The five-session sample is a quick rejection screen, not an independent large sample.
- The archive is historical and does not establish current market behavior.

## Next required data for genuine order-flow research

A genuine buyer/seller pressure test requires trade-level data with aggressor side (or a defensible trade-signing method), and ideally best bid/ask plus order-book depth. OHLCV alone cannot tell whether reported volume was buyer-initiated or seller-initiated.

**Decision: reject these OHLCV proxies. Do not add them to MOEX EDGE, Telegram, or options selection.** If a reliable aggressor-side dataset becomes available, test it separately with a pre-registered chronological split and realistic per-symbol costs.

## Scope and safety

Research-only, read-only historical test. No production files, scheduled workflows, Telegram settings, Finam executor, broker integration, secrets, or real orders were changed.
