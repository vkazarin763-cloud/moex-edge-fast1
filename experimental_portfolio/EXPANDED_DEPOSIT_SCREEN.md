# Expanded weekly strategy and deposit screening

## Research grid

The batch evaluates 13 predeclared rule variants:
- Buy and hold.
- Simple moving-average trend: 10, 20 and 40 weeks.
- Momentum: 13, 26 and 52 weeks.
- Mean reversion: 2, 4 and 8 weeks.
- Price breakout: 13, 26 and 52 weeks.

Each is evaluated at 0.10%, 0.25% and 0.50% illustrative one-way turnover costs. These are sensitivity assumptions, not confirmed account-specific execution costs. This expands the matrix to 39 rows per instrument.

The parameter grid is deliberately small and explicit. Selecting the best variant after inspecting the same data would introduce multiple-testing/selection bias. All variants must be reviewed across rolling folds and parameter neighborhoods; this grid alone cannot establish a robust edge.

## Deposit screen

The script preserves up to five years of weekly bars for indicator warm-up, but evaluates strategy returns only over the trailing approximately 52 weeks. It then compares each strategy's historical trailing-window CAGR with the current 181-day-to-one-year RUB deposit hurdle (12.85% annualized in the 27 Nov 2026 Bank of Russia snapshot).

Each JSON/CSV result contains strategy CAGR and max drawdown, illustrative one-way cost, deposit hurdle and excess return, status (BELOW_HURDLE, ABOVE_HURDLE_NOT_APPROVED or NOT_COMPARABLE), and the labels trailing_approx_52_weeks and historical_screen_only_not_forecast.

The trailing strategy return and current deposit rate are not a synchronized forward investment comparison. This screen is a conservative rejection filter, not a forecast, net-of-tax result or approval. A proper historical comparison requires a historical term-specific deposit-rate series and matched rollover assumptions. Actual bank offers, tax, fees, spread, slippage and liquidity must be modeled before decision-making.

## Safety and scope

- Read-only Finam account permission and historical market-data access.
- No order endpoints, order placement, leverage, position sizing or live execution.
- Candidate eligibility is not strategy approval.
- Bonds, futures and options remain outside this equity/fund weekly model until dedicated cash-flow, expiry, margin and payoff models are implemented.
