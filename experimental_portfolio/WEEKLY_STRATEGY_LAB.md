# Weekly Strategy Lab (paper research)

Five deterministic strategies: buy-and-hold, 20-week SMA trend, 13-week momentum, 4-week mean-reversion and 13-week breakout.

Signals are formed at close and applied to the next bar's close-to-close return (one-bar lag, no look-ahead). Turnover costs are charged on changes in exposure. Stress assumptions: 10, 25 and 50 basis points one-way; not actual Finam fee estimates.

Metrics: total return, CAGR, max drawdown, annualized volatility, Sharpe (zero risk-free assumption), exposure, turnover. No leverage, sizing, broker connection, or orders.

Limitations: simplified close-to-close execution, corporate actions, spreads/liquidity, market impact, survivorship, data provenance and stability must be considered. This is not a recommendation. A later selection stage must include chronological train/validation/test splits and a benchmark.
