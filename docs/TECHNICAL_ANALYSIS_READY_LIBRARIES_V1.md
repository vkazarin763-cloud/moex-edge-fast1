# MOEX EDGE — ready-made technical analysis adapter v1

## Decision

Use the MIT-licensed, community-maintained **Pandas TA Classic** package as the first external dependency. The pinned initial dependency is recorded in `requirements-ta-research.txt`.

The package provides native Python implementations of 62 candlestick patterns and a broad indicator library (including EMA, RSI, ATR, ADX and volume indicators). Its official project documentation states that the candlestick implementations do not require TA-Lib.

Reference: https://github.com/xgboosted/pandas-ta-classic

## Why pytrendline is not a runtime dependency yet

The upstream `pytrendline` project can detect support/resistance trendlines, but its README documents an exhaustive O(N^3) scan and the PyPI release history shows its latest release as 1.0.1 from June 2021. It may be useful for bounded offline experiments, but it is not added to the always-on scanner until its maintenance, runtime and output stability are tested.

References:
- https://github.com/ednunezg/pytrendline
- https://pypi.org/project/pytrendline/

## Current adapter

`research_agent/technical_analysis_ready.py` is isolated and descriptive-only:

- strict OHLCV validation (required columns, finite/positive prices, non-negative volume, unique increasing timestamps, valid OHLC relationships);
- Pandas TA Classic candlestick pattern detections;
- EMA 20/50/200, RSI 14, ATR 14, ADX 14 and relative volume 20;
- support/resistance zones from swing pivots, only available after the configured right-side confirmation bars have closed;
- trailing-window OLS high/low channel classification (up/down/sideways/unstable).

## Safety and data contract

- This is not connected to the active scanner.
- It emits no LONG/SHORT signals and performs no trade execution.
- No holdout data is opened or modified.
- No future bars are used in pivot confirmation or channel fitting.
- Library detections are descriptive features, not evidence of profitability.
- The adapter expects a DataFrame with `timestamp, open, high, low, close, volume`.

## Next validation steps

1. Run the isolated unit tests and dependency installation in GitHub Actions.
2. Feed a small, explicitly selected sample of already available MOEX D1/H1/W1 candles through the adapter.
3. Compare pattern/indicator outputs with independently calculated reference values.
4. Benchmark bounded channel/level calculations across the 44-stock universe.
5. Only after data and runtime checks, consider a separate read-only 44-stock analysis workflow. Promotion to signal generation requires separate chronological walk-forward and holdout validation.
