# Expanded historical options research

**Research only.** This workflow expands the earlier Finam sample by collecting near-ATM CALL/PUT contracts across up to two expiries 15–365 DTE for SBER, GAZP, LKOH, ROSN and MOEX. It fetches M5/H1 (30-day) and D1 (365-day) trade-derived OHLCV bars, plus underlying H1/D1 bars.

It then runs a parameter grid for option-price breakouts and EMA crosses with 3/6/12/24-bar holding periods, 20/30/50% stops, 30/50/100% targets and hypothetical 2/5/10% round-trip cost sensitivities.

## Important limits
- Historical executable bid/ask and orderbook snapshots are not provided by these bars.
- Cost assumptions are sensitivities, not actual observed spread/fees.
- Contract selection is based on current chain/spot, causing selection bias.
- Sparse histories may produce tiny trade samples. Ranking is not evidence of profitability.
- The script resolves same-bar stop/target collisions pessimistically (stop first).
- No orders, accounts, portfolio endpoints, scheduler, Telegram, or live trading are touched.

Manual workflow only, using existing `FINAM_API_SECRET`. Artifacts retained 30 days. No schedule.

## Finam chain endpoint behavior
The official REST documentation for `GET /v1/assets/{underlying_symbol}/options` defines optional `expiration_date.year/month/day` filters. A month can be requested with `day=0`; without an expiry filter the endpoint returns the nearest expiry only. The collector now probes the unfiltered nearest chain, derives candidate root strings from the actual returned option symbols (for example, `SR...` yields candidate `SR`), and tests those candidates alongside a no-root control for each calendar month intersecting the 15–365 DTE window. These are diagnostic probes, not assumed valid root semantics. Each request records its root, HTTP status, returned count and expiry dates. This distinguishes an empty date-filter result from a root-specific result and scans a full year of expiries.

Official reference: https://api.finam.ru/docs/rest/assetsservice_optionschain.md
