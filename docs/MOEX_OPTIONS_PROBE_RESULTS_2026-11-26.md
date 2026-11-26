# MOEX options read-only probe results — 2026-11-26

## Scope and safety

- Provider: Finam Trade API.
- Generated: 2026-11-26T18:53:12.740363Z.
- Code revision tested: `67a9e85c1a9ed832e4b20c212c56073a5852c6dd`.
- Underlyings: GAZP, SBER, ROSN, MOEX.
- Expiries: 2026-12-16 and 2027-01-20 (the primary 20–60 day research window as of 2026-11-26).
- Up to 12 near-ATM contracts sampled per underlying/expiry; 84 option quote requests represented in the artifact.
- Mode: read-only market data. `order_endpoints_called=false`; no account or order endpoints were called.
- All five GitHub Actions workflows for the tested code revision completed successfully: Research Agent Safety Tests, Finam AI Screener MCP Probe (Read Only), Manual Groq Fallback Routing Check (Offline), Finam Executor Safety Tests, and MOEX Options Read-Only Data Probe.

## Results

All 84 sampled contracts returned a positive, non-crossed bid/ask pair. This confirms that the quote endpoint is returning two-sided quote fields, but does not establish that the quotes are fresh, executable, or supported by sufficient market depth.

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

The only two contracts in the full sample that simultaneously had a quote age <= 5 minutes and a spread < 10% were MOEX calls/puts:
- `ME140CL6@RTSX`: spread 4.863%, quote age 0 seconds, displayed bid/ask sizes 1000/1000, open interest 0.
- `ME190CX6@RTSX`: spread 4.082%, quote age 0 seconds, displayed bid/ask sizes 1000/1000, open interest 60.

For both contracts, the probe returned no order-book data and no latest-trades data. Therefore, these two quote snapshots are not enough to establish executable liquidity. The tighter GAZP and SBER quotes were stale (older than five minutes); ROSN had no sampled contract below the 10% spread threshold.

### 2027-01-20 by underlying

| Underlying | Samples | Fresh <= 5 min | Spread < 10% |
|---|---:|---:|---:|
| GAZP | 12 | 12 | 0 |
| SBER | 12 | 9 | 0 |
| ROSN | 12 | 12 | 0 |
| MOEX | 0 | — | — |

All 36 sampled quotes for this expiry had spreads of at least 25.35%; median spread was 112.62%. No sampled contract passed the preliminary spread threshold.

## Decision

**Finam's current read-only feed has not yet demonstrated a sufficiently liquid, executable option contract for this strategy. Do not generate signals or start a profitability backtest from this sample.**

The two apparently attractive fresh MOEX quotes lack order-book and trade confirmation, and one has zero open interest. The other narrow-spread quotes are stale. The January expiry quotes are fresh in many cases but prohibitively wide by the preliminary filter.

Do not replace missing executable market data with Black–Scholes theoretical marks. The existing `options_backtest.py` remains unsuitable as evidence of option-strategy profitability.

## Next bounded step

Treat this feed as **insufficient for a verified options strategy at present**. If further investigation is justified, the only useful next check is to establish why the Finam order-book/trades endpoints are empty for the fresh MOEX contracts and whether a second live snapshot confirms their depth. If that cannot be established from the existing free read-only access, stop this route rather than running repeated broad probes or adding a paid data source without a separate decision.
