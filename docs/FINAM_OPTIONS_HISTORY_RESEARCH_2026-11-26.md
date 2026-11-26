# Finam options historical data probe — 2026-11-26

## Status

Research-only. This branch uses the existing FINAM_API_SECRET already present in this repository. No new secret was created or printed. The workflow never calls account, portfolio, order, cancel, or SL/TP endpoints. It performs session authentication and market-data GET requests only.

Workflow: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45885560779
Artifact: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45885560779/artifacts/15149226606

## Data availability discovered

Finam Trade API returns option chains and historical OHLCV trade bars for MOEX options. It also exposes current LastQuote, OrderBook, and LatestTrades endpoints.

Tested underlyings: SBER, GAZP, ROSN, MOEX.
Tested expiries: 2026-12-16 and 2027-01-20.

| Underlying | Contracts in 2026-12-16 chain | Contracts in 2027-01-20 chain |
|---|---:|---:|
| SBER | 34 | 24 |
| GAZP | 98 | 64 |
| ROSN | 120 | 72 |
| MOEX | 24 | 0 |

Nearest-to-ATM contracts selected for 2026-12-16:

| Underlying | Option | OI | M5 bars | H1 bars | D1 bars | Current bid/ask spread |
|---|---|---:|---:|---:|---:|---:|
| SBER | SR290CL6 CALL | 75,348 | 71 | 53 | 48 | 11.76% |
| SBER | SR290CX6 PUT | 15,716 | 83 | 59 | 26 | 11.00% |
| GAZP | GZ100CL6 CALL | 81,256 | 95 | 64 | 58 | 51.61% |
| GAZP | GZ100CX6 PUT | 225,568 | 169 | 99 | 51 | 0.31% |
| ROSN | RN330CL6 CALL | 6,966 | 22 | 17 | 11 | 33.26% |
| ROSN | RN330CX6 PUT | 12,500 | 29 | 23 | 7 | 18.67% |
| MOEX | ME160CL6 CALL | 6,166 | 11 | 10 | 7 | 77.00% |
| MOEX | ME160CX6 PUT | 5,994 | 7 | 6 | 5 | 108.17% |

The 2027-01-20 series were much thinner: SBER CALL had 9 M5/8 H1/3 D1 bars, SBER PUT had no bars, GAZP contracts had only 1–3 bars, ROSN had no bars, and MOEX had no contracts.

## Current book and trade activity

- GAZP PUT GZ100CX6 is the strongest current liquidity candidate in this sample: bid 3.22 / ask 3.23 (0.31% spread), displayed best-level sizes 100 bid and 194 ask, OI 225,568, and 536 timestamped trades in the API response.
- Its latest trade was at 2026-11-26 16:44:49 UTC (about 173 minutes before the 19:37 UTC probe). The best order-book level update was at 19:26:40 UTC (about 11 minutes before the probe).
- GAZP CALL GZ100CL6 was much worse: 51.61% spread and best-level sizes 10 bid / 5 ask.
- SBER CALL/PUT spreads were about 11%; ROSN spreads 18.67–33.26%; MOEX spreads 77–108%.
- LatestTrades returned actual timestamped trade records, not snapshot records, for the sampled 2026-12-16 contracts. The number of returned trades varied from 7 (MOEX PUT) to 746 (GAZP CALL).
- OrderBook and LatestTrades are current market-data endpoints. They do not provide a historical bid/ask order-book archive.

## Exploratory trade-print replay

A strict preliminary proxy was run using actual option trade prints and underlying Finam D1/H1 bars.

Rules:
- Underlying direction: EMA20/EMA50 on D1 and H1.
- Count only transitions into a new direction.
- Use the 2026-12-16 nearest-to-ATM CALL for LONG or PUT for SHORT.
- Historical moneyness must be within 5% of the underlying close on the signal date.
- Entry: first actual option trade within 24 hours after the signal day's last completed underlying H1 bar.
- Exit: first actual option trade within 24 hours after the 1/3/5-session target day's last completed underlying H1 bar.
- One active trade per underlying/method/horizon; do not reuse an entry trade.

| Method | Horizon | Completed observations | Positive | Mean trade-price return |
|---|---:|---:|---:|---:|
| D1-only | 1 session | 0 | — | — |
| D1-only | 3 sessions | 0 | — | — |
| D1-only | 5 sessions | 0 | — | — |
| H1-only | 1 session | 5 | 0 | -24.79% |
| H1-only | 3 sessions | 2 | 1 | +47.15% |
| H1-only | 5 sessions | 3 | 2 | +58.18% |
| D1+H1 confirmed | 1 session | 2 | 0 | -21.95% |
| D1+H1 confirmed | 3 sessions | 2 | 1 | +47.15% |
| D1+H1 confirmed | 5 sessions | 3 | 2 | +58.18% |

These very small samples are not statistically meaningful. The positive 3/5-session means are dominated by one ROSN PUT trade-print outlier (+155.69% / +235.84%), while the worst observed outcome was -68.72%. All completed one-session observations in the strict sample were negative.

## Critical limitations

1. Trade prints are not historical executable ask/bid quotes. A hypothetical order may not have filled at the observed print price.
2. No historical spread, queue position, fill probability, fees, or slippage is included.
3. The selected contracts were chosen from the current chain and then filtered by historical moneyness; this is not equivalent to selecting the nearest-to-ATM contract independently on each historical signal date. Residual selection bias remains.
4. The LatestTrades endpoint returns a finite recent trade history, not a guaranteed complete exchange tape.
5. The sample contains very few independent events and highly variable option prices.

## Decision

- Finam is a usable source of actual option OHLCV bars and recent trade prints. This removes the earlier assumption that no historical option prices are accessible at all.
- It does **not** solve the historical executable bid/ask problem.
- GAZP PUT GZ100CX6 is the best current liquidity candidate in this four-underlying sample, but its latest trade was about 2.9 hours old at the probe time. This is a watchlist candidate only, not a trade recommendation.
- No strategy is approved. The preliminary trade-print proxy does not demonstrate a robust profitable edge.
- Do not activate signals, Telegram delivery, order execution, or scheduling from this research.

## Official API references

- Finam Trade API REST: https://api.finam.ru/docs/rest/
- Finam Bars: https://api.finam.ru/docs/grpc/bars.md
- Finam OrderBook (current book): https://api.finam.ru/docs/grpc/orderbook.md
- Finam LatestTrades: https://api.finam.ru/docs/grpc/latesttrades.md
