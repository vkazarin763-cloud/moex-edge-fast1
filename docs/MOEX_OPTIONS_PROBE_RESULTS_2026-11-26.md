# MOEX options read-only probe results — 2026-11-26

## Scope and safety

- Provider: Finam Trade API.
- Broad snapshot: 2026-11-26T18:53:12.740363Z; code revision `67a9e85c1a9ed832e4b20c212c56073a5852c6dd`.
- Targeted snapshot: 2026-11-26T19:03:12.384482Z; branch head `e61f3aa0b6d524509498d30f1300655c1dbd38f1`, including targeted diagnostic code commit `3540662f7500cf3659cc27e3d9587657c77207ee`.
- Underlyings: GAZP, SBER, ROSN, MOEX.
- Expiries: 2026-12-16 and 2027-01-20 (primary 20–60 day research window as of 2026-11-26).
- Broad sample: up to 12 near-ATM contracts per underlying/expiry; 84 option quote requests.
- Targeted diagnostic: order book and latest trades requested for both MOEX candidates that passed the fresh/narrow-spread screen, plus one baseline contract per underlying.
- Mode: read-only market data. `order_endpoints_called=false`; no account or order endpoints were called.
- All five GitHub Actions workflows for the targeted run's branch head completed successfully: options probe, Research Agent Safety Tests, Finam AI Screener MCP Probe (Read Only), Manual Groq Fallback Routing Check (Offline), and Finam Executor Safety Tests.

## Broad quote results

All 84 sampled contracts returned a positive, non-crossed bid/ask pair. This confirms two-sided quote fields were returned, but does not establish that quotes are fresh, executable, or supported by sufficient market depth.

| Expiry | Samples | Fresh quotes (age <= 5 min) | Spread < 10% of mid | Both fresh and spread < 10% | Median spread |
|---|---:|---:|---:|---:|---:|
| 2026-12-16 | 48 | 14 | 11 | 2 | 24.38% |
| 2027-01-20 | 36 | 33 | 0 | 0 | 112.62% |

### 2026-12-16 by underlying

| Underlying | Samples | Fresh <= 5 min | Spread < 10% |
|---|---:|---:|---:|
| GAZP | 12 | 1 | 3 |
| SBER | 12 | 0 | 6 |
| ROSN | 12 | 6 | 0 |
| MOEX | 12 | 7 | 2 |

The two contracts that simultaneously had a quote age <= 5 minutes and a spread < 10% in the broad sample were:
- `ME140CL6@RTSX`: initial spread 4.863%, initial quote age 0 seconds, displayed bid/ask sizes 1000/1000, open interest 0.
- `ME190CX6@RTSX`: initial spread 4.082%, initial quote age 0 seconds, displayed bid/ask sizes 1000/1000, open interest 60.

### Targeted order-book and trade results

The corrected probe explicitly queried both candidates. The earlier broad snapshot had not queried these symbols for order-book/trade data; absence in that artifact did not mean the endpoints were empty.

**ME140CL6@RTSX — CALL**
- Fresh quote: bid 21.69 / ask 22.77; spread 4.858%; quote age 0 seconds.
- Displayed bid/ask sizes: 1000 / 1000.
- Open interest: 0.
- Order book: 2 rows; current bid and ask matched the quote, with both sides timestamped 2026-11-26 19:03:13 UTC.
- Latest trades: request failed with Finam HTTP 499 (reported as “Unknown”).
- Interpretation: a current two-sided book snapshot exists, but zero open interest and unavailable trade history do not establish active trading liquidity.

**ME190CX6@RTSX — PUT**
- Fresh quote: bid 27.34 / ask 28.48; spread 4.085%; quote age 0 seconds.
- Displayed bid/ask sizes: 1000 / 1000.
- Open interest: 60.
- Order book: 3 rows; current best bid 27.34 and ask 28.48 matched the quote and were timestamped 2026-11-26 19:03:13 UTC. An additional old bid at 5.15 was also present.
- Latest trades: one trade returned, dated 2026-11-18 19:36:12 UTC, price 24.68, size 30. The trade is about eight days older than the snapshot.
- Interpretation: this is the stronger of the two candidates because it has nonzero open interest and a current two-sided book. However, the only returned trade is stale; recent execution activity is not demonstrated.

The tighter GAZP and SBER quotes were stale (older than five minutes); ROSN had no sampled contract below the 10% spread threshold.

### 2027-01-20 by underlying

| Underlying | Samples | Fresh <= 5 min | Spread < 10% |
|---|---:|---:|---:|
| GAZP | 12 | 12 | 0 |
| SBER | 12 | 9 | 0 |
| ROSN | 12 | 12 | 0 |
| MOEX | 0 | — | — |

All 36 sampled quotes for this expiry had spreads of at least 25.35%; median spread was 112.62%. No sampled contract passed the preliminary spread threshold.

## Current decision

**ME190CX6@RTSX is a watchlist candidate for further data validation, not a verified trade.** The current book is two-sided and the quote is fresh, but open interest is only 60 and the latest reported trade is about eight days old. ME140CL6@RTSX is weaker due to zero open interest and an HTTP 499 error on the latest-trades request.

This evidence is not enough for a credible historical profitability backtest: there is no historical sequence of executable bid/ask snapshots, and no recent trade confirmation for the candidate. Do not generate live signals or claim profitability. Do not replace executable market data with Black–Scholes theoretical marks; the existing `options_backtest.py` remains unsuitable as evidence of option-strategy profitability.

## Bounded next decision

Do not repeat the broad scan. If continuing with existing free read-only access, the only useful next check is to capture a small number of time-separated snapshots for `ME190CX6@RTSX` and verify whether its best bid/ask and depth persist and whether recent trades appear. If that cannot be established, stop this Finam options-data route. No paid data source, account endpoint, order, or production workflow is involved.
