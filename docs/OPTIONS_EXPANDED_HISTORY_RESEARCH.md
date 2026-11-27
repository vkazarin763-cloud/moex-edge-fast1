# Expanded historical options research

**Research only.** This workflow expands the earlier Finam sample by collecting near-ATM CALL/PUT contracts across up to two expiries 15–90 DTE for SBER, GAZP, LKOH, ROSN and MOEX. It fetches M5/H1 (30-day) and D1 (365-day) trade-derived OHLCV bars, plus underlying H1/D1 bars.

It then runs a parameter grid for option-price breakouts and EMA crosses with 3/6/12/24-bar holding periods, 20/30/50% stops, 30/50/100% targets and hypothetical 2/5/10% round-trip cost sensitivities.

## Important limits
- Historical executable bid/ask and orderbook snapshots are not provided by these bars.
- Cost assumptions are sensitivities, not actual observed spread/fees.
- Contract selection is based on current chain/spot, causing selection bias.
- Sparse histories may produce tiny trade samples. Ranking is not evidence of profitability.
- The script resolves same-bar stop/target collisions pessimistically (stop first).
- No orders, accounts, portfolio endpoints, scheduler, Telegram, or live trading are touched.

Manual workflow only, using existing `FINAM_API_SECRET`. Artifacts retained 30 days. No schedule.
