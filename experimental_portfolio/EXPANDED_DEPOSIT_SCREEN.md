# Expanded weekly strategy and validation screen

## Strategy grid
The batch evaluates 13 predeclared rule variants: buy-and-hold; SMA trend (10/20/40 weeks); momentum (13/26/52); mean reversion (2/4/8); breakout (13/26/52). Each is tested at 0.10%, 0.25% and 0.50% illustrative one-way turnover costs. These are sensitivity assumptions, not confirmed account-specific costs.

## Critical return-data limitation
Finam's documented weekly-bars schema provides OHLCV and a snapshot flag, but does not expose a documented total-return/adjusted-price flag. Finam separately documents historical dividend and split endpoints. The audit collector was added, but its first run returned HTTP 400 for every dividend and split request; no corporate-action records were retrieved. The first implementation percent-encoded dots in documented query parameter names (for example, `date_from.year`); the collector now preserves literal dots and adds a regression test. A fresh live batch must confirm the fix before the event feed can be considered usable.

Finam's protobuf schema defines the historical dividend `date` as the **register closing date**, not the ex-dividend/last-buy date. It must not be used directly as the price-adjustment date. Split `exec_date` is the effective corporate-action date. Fund-distribution completeness and authoritative ex-date mapping remain unverified. No events are applied to OHLCV. Until corporate actions are reconciled and fund distributions are verified, raw price CAGR is **not comparable** with a deposit return. Every deposit comparison remains `NOT_COMPARABLE`; raw-price metrics are diagnostic only. Do not treat previously observed above-hurdle rows as candidates.

Official API references:
- [Finam REST API: bars, historical dividends and splits](https://api.finam.ru/docs/rest/)
- [Finam protobuf market-data schema](https://github.com/FinamWeb/finam-trade-api/blob/main/proto/grpc/tradeapi/v1/marketdata/marketdata_service.proto)
- [Finam corporate-actions protobuf schema](https://github.com/FinamWeb/finam-trade-api/blob/main/proto/grpc/tradeapi/v1/corporateactions/corporate_actions_service.proto)

## Corporate-action event audit

The read-only batch collects `/v1/past-dividends` for qualified equities and funds and `/v1/splits/past` for qualified equities, using paginated requests. Requests are throttled below Finam's documented 200 requests/minute ceiling. The event data is retained in the research artifact with per-endpoint status; it is not used to adjust prices. Missing, unsupported or incomplete event feeds keep total-return and deposit comparisons disabled.

## Sequential holdout validation
The research batch preserves up to five years of weekly history. For each fixed strategy rule it now evaluates sequential holdout folds after a 104-week warm-up, using up to 52-week test windows (minimum 26 weeks). Signals are calculated from information available up to the prior bar; no parameters are fitted on the test fold. This is a more informative stability check, but not proof of future profitability. The folds remain historical and can overlap neither training nor future information in the signal calculation.

A low-volatility Sharpe ratio is suppressed when annualized volatility is below 5%; it is labelled `LOW_VOLATILITY_UNRELIABLE` rather than presented as a meaningful risk-adjusted score. This specifically prevents smooth money-market NAV series from producing misleadingly impressive Sharpe values.

## Deposit screen
The earlier comparison used a trailing strategy return against a current deposit snapshot; it was not synchronized. It is now explicitly disabled until total-return adjustments are verified. A proper comparison also needs historical term-specific deposit rates, matched rollover assumptions, taxes, and actual fees/spread/slippage.

## Safety and scope
Read-only account permission and market-data endpoints only. No order endpoints, leverage, position sizing, live execution or paid data services. Equities/funds remain a research-only phase; bonds, futures and options require dedicated cash-flow, expiry, margin and payoff models.
