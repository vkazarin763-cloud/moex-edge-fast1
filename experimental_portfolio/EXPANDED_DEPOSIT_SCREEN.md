# Expanded weekly strategy and validation screen

## Strategy grid
The batch evaluates 13 predeclared rule variants: buy-and-hold; SMA trend (10/20/40 weeks); momentum (13/26/52); mean reversion (2/4/8); breakout (13/26/52). Each is tested at 0.10%, 0.25% and 0.50% illustrative one-way turnover costs. These are sensitivity assumptions, not confirmed account-specific costs.

## Critical return-data limitation
Finam's documented weekly-bars schema provides OHLCV and a snapshot flag, but does not expose a documented total-return/adjusted-price flag. Finam separately documents historical dividend and split endpoints. Until corporate actions are retrieved, reconciled and applied (and fund distributions are verified), raw price CAGR is **not comparable** with a deposit return. The batch therefore marks every deposit comparison `NOT_COMPARABLE` and preserves the raw-price screen only as diagnostic metadata. Do not treat previously observed above-hurdle rows as candidates.

Official API references:
- [Finam REST API: bars, historical dividends and splits](https://api.finam.ru/docs/rest/)
- [Finam protobuf market-data schema](https://github.com/FinamWeb/finam-trade-api/blob/main/proto/grpc/tradeapi/v1/marketdata/marketdata_service.proto)

## Sequential holdout validation
The research batch preserves up to five years of weekly history. For each fixed strategy rule it now evaluates sequential holdout folds after a 104-week warm-up, using up to 52-week test windows (minimum 26 weeks). Signals are calculated from information available up to the prior bar; no parameters are fitted on the test fold. This is a more informative stability check, but not proof of future profitability. The folds remain historical and can overlap neither training nor future information in the signal calculation.

A low-volatility Sharpe ratio is suppressed when annualized volatility is below 5%; it is labelled `LOW_VOLATILITY_UNRELIABLE` rather than presented as a meaningful risk-adjusted score. This specifically prevents smooth money-market NAV series from producing misleadingly impressive Sharpe values.

## Deposit screen
The earlier comparison used a trailing strategy return against a current deposit snapshot; it was not synchronized. It is now explicitly disabled until total-return adjustments are verified. A proper comparison also needs historical term-specific deposit rates, matched rollover assumptions, taxes, and actual fees/spread/slippage.

## Safety and scope
Read-only account permission and market-data endpoints only. No order endpoints, leverage, position sizing, live execution or paid data services. Equities/funds remain a research-only phase; bonds, futures and options require dedicated cash-flow, expiry, margin and payoff models.
