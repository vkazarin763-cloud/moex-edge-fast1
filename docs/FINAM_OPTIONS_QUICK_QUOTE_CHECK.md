# Quick Options Quote Check

This workflow runs the existing read-only Finam quote/order-book collector for a short window.

- Default duration: 2 minutes
- Default poll interval: 30 seconds
- Symbols: GAZP PUT `GZ100CX6@RTSX` and SBER PUT `SR290CX6@RTSX`
- Captures current quote and order book snapshots; no order/account endpoints.
- Artifact: JSONL, retained 30 days.

This is a quick liquidity/spread check, not a backtest or profitability proof. Snapshots cannot guarantee execution or queue position.
