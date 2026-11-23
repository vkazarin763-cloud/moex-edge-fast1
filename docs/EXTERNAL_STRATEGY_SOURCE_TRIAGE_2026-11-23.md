# External strategy source triage — 2026-11-23

## Scope and evidence boundary

This is a manual source review of the 23 metadata leads produced by run `45254093291`. It does not validate profitability on MOEX. Public claims and published backtests are treated as source claims, not independently reproduced results. No market data was downloaded and no signals were generated.

## Findings

### Equities

#### Candidate: Jason IE — Multi-Indicator Composite Signal System
- Source: https://github.com/jason-ie/trading-strategy
- Source type: documented daily long/short equity strategy, not merely a backtesting framework.
- Universe in source: PLTR, TSLA, HOOD; SPY benchmark. The author explicitly targets high-beta growth equities.
- Extracted indicators:
  - Mean reversion: Johnson-SU distribution fitted by maximum likelihood to the estimation sample; +1 below the 5th percentile, -1 above the 95th percentile.
  - RSI(14), Wilder smoothing: +1 above 70 and -1 below 30 (momentum interpretation).
  - Ichimoku: four-part alignment (Tenkan/Kijun cross, price vs cloud, cloud color, Chikou confirmation).
  - ATR(14): short-only activity gate, true range above rolling ATR.
- Entry: long when MR + RSI + Ichimoku >= 1; short when the sum <= -1 and ATR gate passes. Entries execute next day.
- Validation claimed by source: rolling 24-month estimation / 6-month non-overlapping test windows, step 6 months; five reported windows, four classified YES and one positive.
- Missing from README-level specification: complete deterministic exit/stop/target rules, exact portfolio constraints and source-data reconstruction details. These must be extracted from the notebook/code before implementation.
- MOEX assessment: potentially adaptable for daily stock research, but original universe is only three US high-beta names. No evidence yet that its factor thresholds transfer to MOEX.
- Status: `SOURCE_REVIEWED`; extraction incomplete; not eligible for signal scanner.

#### Other initial equities leads
The first scout batch included several backtesting engines rather than fully specified trading strategies, plus unrelated publication matches (including an oil-futures title tagged as equities and an ETH/USDT study). These are search false positives and must not be treated as strategy candidates.

### Futures

#### Negative-control source: Stellar Research — Strategy Autopsy
- Source: https://github.com/stellar-research/strategy-autopsy
- Market/data: ES, MES and NQ futures; published tests span 2010–2025.
- Methodological value: rules registered before testing, locked out-of-sample period, random-entry baseline, commission/slippage and slippage sensitivity.
- Findings reported by source: the tested Al Brooks and ICT/SMC rule sets did not show a reliable edge after costs. Example: one ES setup beat its random baseline before costs but had profit factor 0.91 after costs; the tested ICT model averaged approximately -0.18R / -0.24R after costs on ES/NQ.
- MOEX assessment: do not port these rules as positive candidates. Retain the repository as a negative-control and validation-method reference.
- Status: `REJECTED_NO_EDGE_IN_SOURCE_MARKET` for strategy promotion; validation methodology may be reused after independent review.

#### Remaining initial futures leads
The first catalog mostly surfaced platforms, stock screeners, generic futures chapters and broad framework repositories rather than concrete, fully specified futures strategies. The VIX futures basis paper is a different underlying/market structure and is not yet an adaptable MOEX FORTS candidate. Search coverage needs improvement.

### Options

#### Candidate: CuteMarkets — c36_quality
- Source: https://github.com/cutemarkets/cute-intraday-option-strats
- Exact model: `c36_vwap_mr_option_native_quality_v1`, single-leg options, 0–2 DTE (target 1 DTE), default underlyings SPY/QQQ.
- Signal family: intraday VWAP residual z-score mean reversion.
- Extracted signal parameters: 5-minute opening-range context; entry scan 09:35–12:00 ET; exit cutoff 15:55 ET; rolling residual sigma window 20; entry excursion z-score 1.35 and reclaim 0.65; relative opening volume >= 1.05; residual volatility ratio 0.0005–0.016; 3-bar VWAP slope absolute limit 0.002; reversal candle required.
- Long signal: previous z-score <= -1.35 and current >= -0.65, or low reaches VWAP - 1.35 sigma and close reclaims VWAP - 0.65 sigma, with bullish candle. Short is symmetric.
- Entry: next bar open.
- Exit: stop, z-score target 0.15, opposite-color candle after 3-minute minimum hold, max hold 25 minutes, 15:55 time exit, or session close.
- Option-side constraints: 0–2 DTE, minimum option bar volume 25, minimum premium 0.60, max entry-bar range 35%, minimum quote and chain coverage 35%, quote-aware fills.
- Source also reports OOS evidence for its US research window; this is not independently reproduced and is not evidence of MOEX profitability.
- MOEX assessment: the underlying VWAP residual signal can be studied as a research hypothesis, but US ETF microstructure, 0–2DTE contract assumptions and option quote model cannot be copied to MOEX. Requires real historical MOEX option chains/quotes and instrument-specific contract rules. Until those data are verified, options status is `DATA_NOT_READY`.
- Status: `EXTRACTED` at source-rule level; `DATA_NOT_READY` for MOEX option adaptation/backtest; not eligible for signals.

#### Candidate: randomwalkhan — Short-Term Reversal Strategy
- Source: https://github.com/randomwalkhan/Short-Term-Reversal-Strategy
- Source describes a short-term reversal call-buying approach after large intraday drawdowns, with historical recovery-probability filters, near-ATM calls around 30 DTE in research, option liquidity gates and no-trade behavior when quotes are not executable.
- Published version notes include 60-day lookback, at least 10 matched signals, current drop >0.5%, timing score >=0.50, and live option liquidity gates (OI >=110, volume >=20, spread <=14%). Research and live-paper exit ladders differ.
- Major transfer limitations: US QQQ/leveraged ETF universe, US listed option conventions, and source-reported performance is not independently verified. The repository contains research notebooks and live-paper iterations; the exact current research-vs-live rule set must be pinned to a commit before rule extraction is considered complete.
- MOEX assessment: possible conceptual research on the underlying only; option execution is `DATA_NOT_READY` until real historical MOEX option chain and bid/ask data are available.
- Status: `SOURCE_REVIEWED`; exact immutable version and complete rule set still require extraction; not eligible for signals.

## Corrections required in the discovery pipeline

1. Do not infer market tags from the search query alone. Validate each result against repository description, README/title and explicit instruments.
2. Separate strategy implementations from backtesting engines, APIs, screeners, educational chapters and generic infrastructure.
3. Crossref title matches must be checked for actual asset class; title-only matches can be misleading.
4. Store source commit SHA / DOI version, access date, license evidence, instrument universe, timeframe and explicit entry/exit rule coverage.
5. A strategy is not `EXTRACTED` until entry, exit, invalidation, timeframe, parameters and execution assumptions are all accounted for. Missing rules must remain `INCOMPLETE`.
6. Source-reported backtest metrics must be stored as claims with citations and never represented as MOEX test results.

## Recommended next actions

1. Improve source discovery queries and tagging to find actual strategy implementations rather than frameworks.
2. Finish extraction from the Jason IE notebook and pin the exact randomwalkhan strategy version.
3. Search for concrete FORTS strategy rule sets; current futures batch is insufficient.
4. Keep all three market scanners disabled for these candidates until independent MOEX validation passes. For options, first prove availability and quality of historical option-chain/quote data.
