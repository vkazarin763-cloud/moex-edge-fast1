# MOEX options read-only probe results — 2026-11-26

## Scope and safety

- Provider: Finam Trade API.
- Snapshot generated: 2026-11-26T18:53:12.740363Z.
- Data/code revision: `67a9e85c1a9ed832e4b20c212c56073a5852c6dd`.
- Underlyings: GAZP, SBER, ROSN, MOEX.
- Expiries: 2026-12-16 and 2027-01-20 (primary 20–60 day research window as of 2026-11-26).
- Up to 12 near-ATM contracts sampled per underlying/expiry; 84 option quote requests represented in the artifact.
- Mode: read-only market data. `order_endpoints_called=false`; no account or order endpoints were called.
- All five GitHub Actions workflows for the tested code revision completed successfully.

## Quote results

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

The only two contracts in the full sample that simultaneously had a quote age <= 5 minutes and a spread < 10% were:
- `ME140CL6@RTSX`: spread 4.863%, quote age 0 seconds, displayed bid/ask sizes 1000/1000, open interest 0.
- `ME190CX6@RTSX`: spread 4.082%, quote age 0 seconds, displayed bid/ask sizes 1000/1000, open interest 60.

**Important diagnostic limitation:** the probe revision used for this snapshot requested order-book and latest-trades data only for the first selected contract per underlying. For MOEX that baseline contract was `ME160CX6@RTSX`, not either of the two contracts above. Therefore, the artifact contains no order-book/trade result for `ME140CL6@RTSX` or `ME190CX6@RTSX`; those endpoints were not queried for these two symbols. Their liquidity is unknown, not disproven.

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

**No contract has yet been confirmed as executable, and no profitability backtest or signal generation is justified.** The two MOEX candidates require direct order-book and latest-trades checks before any liquidity conclusion can be made. The other sampled contracts either failed the freshness/spread screen or were too wide.

Do not replace executable market data with Black–Scholes theoretical marks. The existing `options_backtest.py` remains unsuitable as evidence of option-strategy profitability.

## Targeted follow-up

A code correction was committed after this snapshot (`3540662f7500cf3659cc27e3d9587657c77207ee`) so that the next read-only probe will explicitly request order-book and latest-trades data for both `ME140CL6@RTSX` and `ME190CX6@RTSX`, in addition to the baseline diagnostics. Results from that targeted request must be recorded separately; this snapshot does not contain them.

No paid data source, account endpoint, order, or production workflow is involved.
