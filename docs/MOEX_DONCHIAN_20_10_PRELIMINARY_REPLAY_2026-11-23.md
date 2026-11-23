# MOEX EDGE — Donchian 20/10 preliminary replay
Date: 2026-11-23
Status: exploratory only; not scanner-approved

## Scope and provenance

- Market: MOEX shares only.
- Universe: fixed 44-stock list from the project dataset.
- Data artifact: `moex-edge-multi-timeframe-candles`, workflow run 44861047844.
- Snapshot generated: 2026-11-21T03:25:33.304483Z.
- Artifact SHA-256: `6a9ee767f37bec1f9fa9d40d0868ccc8f36b2271dd5ef4a1715f83e4a51af137`.
- D1 source: MOEX ISS TQBR history.
- Holdout policy: exclude every D1 bar dated 2026-11-20 or later. These bars are not used for selection or tuning.

The original artifact validator reported PASS for 44/44 symbols. Independent replay-side validation on the pre-holdout slice found 48,374 D1 bars, zero duplicate timestamps, zero non-monotonic timestamps, zero invalid OHLC rows and zero negative-volume rows.

## Strategy source and exact rules

- External source: https://github.com/bmonagan/backtester
- Immutable source commit: `ba5156ec58f8d240af7b09b476fa8493171228d3`
- License: MIT.
- Source implementation: `TurtleTradingStrategy` inheriting `DonchianBreakoutStrategy`.

Rules tested:
1. Long entry when a completed D1 close is above the highest high of the prior 20 completed bars (current bar excluded).
2. Long exit when a completed D1 close is below the lowest low of the prior 10 completed bars (current bar excluded).
3. Signal is evaluated at close; market order fills at the next available D1 open.
4. Long-only; one position per ticker; no short entries, no protective stop, no pyramiding.

This is the source repository's Turtle System 1-style channel signal only. It is not the complete original Turtle system.

## Corporate-action correction

A first raw-price diagnostic produced impossible split-driven returns. Those raw results were discarded and are not backtest evidence. Before replay, historical OHLC before each effective trading date was converted into post-action price units; volume was adjusted inversely.

| Ticker | Effective first post-action trading date | Action | Historical OHLC factor | Official/source notice |
|---|---:|---|---:|---|
| TRNFP | 2024-02-21 | Split 1:100 | ×0.01 | https://www.moex.com/n67684 |
| GMKN | 2024-04-08 | Split 1:100 | ×0.01 | https://www.moex.com/n68799 |
| VTBR | 2024-07-15 | Consolidation 5000:1 | ×5000 | https://www.moex.com/n71160 |
| PLZL | 2025-03-27 | Split 1:10 | ×0.1 | https://www.moex.com/n88888 |
| T | 2026-04-17 | Split 1:10 | ×0.1 | https://www.moex.com/n99355 |

No trades were evaluated on or after the sealed holdout start. The known action list is not a substitute for a complete issuer corporate-action ledger; all future strategy studies must expand and verify that ledger.

## Preliminary trade-level results

Replay window: 2021-11-22 through 2026-11-19.  
Closed trades: 634 across 44 tickers. Open positions at cutoff: 29.  
Trade holding period median: 22 D1 bars.

These are pooled trade-level diagnostics, not a portfolio return. No CAGR, total portfolio return or capital allocation is inferred.

| Assumed cost per side | Average net trade | Median net trade | Win rate | Profit factor |
|---:|---:|---:|---:|---:|
| 0 bps | 0.903% | -1.907% | 38.0% | 1.248 |
| 8 bps | 0.741% | -2.064% | 37.2% | 1.199 |
| 16 bps | 0.580% | -2.221% | 36.6% | 1.152 |
| 32 bps | 0.259% | -2.533% | 35.8% | 1.064 |

The 8 bps/side case is a sensitivity assumption carried from an earlier project backtest configuration. It is not a verified Finam tariff or measured MOEX bid/ask/slippage cost. The 16/32 bps cases are stress scenarios.

### Stability by exit year (8 bps per side)

| Exit year | Closed trades | Average net trade | Median net trade | Win rate | Profit factor |
|---:|---:|---:|---:|---:|---:|
| 2022 | 98 | -5.005% | -5.368% | 22.4% | 0.216 |
| 2023 | 135 | 8.199% | 3.113% | 60.0% | 5.981 |
| 2024 | 122 | 0.200% | -3.559% | 29.5% | 1.051 |
| 2025 | 155 | 0.137% | -1.654% | 40.0% | 1.038 |
| 2026 through Nov 19 | 124 | -1.550% | -2.864% | 28.2% | 0.597 |

The pooled statistic is dominated by the strong 2023 period. 2022 and 2026 were negative, while 2024–2025 were close to flat after the assumed costs. This is not a stable result.

## Decision

**Status: `EXPERIMENTAL`; do not add to the active scanner.**

Why it does not pass:
- Regime instability is material: several calendar years are negative or close to flat.
- Median trade is negative and win rate is low; results rely on a small number of large winners.
- Cost assumptions are not calibrated to actual MOEX execution.
- Dividends are omitted from price returns.
- The fixed current 44-stock universe applied retrospectively creates universe/survivorship bias.
- The test is not a frozen independent holdout or a full walk-forward promotion test.
- No portfolio accounting, exposure constraints, liquidity/participation model, or drawdown result is established.

## Next verification gates

1. Build a complete, source-backed corporate-action ledger for all 44 tickers; check any remaining extreme price discontinuities.
2. Re-run with verified per-symbol costs/spreads and conservative slippage; report adverse-cost sensitivity.
3. Add dividend cash flows or use a verified total-return series where available.
4. Compare against buy-and-hold and a simple benchmark using explicit, consistent portfolio accounting.
5. Run chronological walk-forward folds and keep the sealed holdout untouched.
6. Compare D1 and W1 versions only as separately registered hypotheses; do not tune the published 20/10 rule on the holdout.
7. Promote only after all predeclared sample, robustness, and independent-review criteria pass.

## Reproducible implementation

The isolated research implementation is `research_agent/moex_equities_donchian_replay.py`; offline unit tests are in `tests/test_moex_equities_donchian_replay.py`. It reads the MOEX multi-timeframe JSON/ZIP artifact and writes a JSON trade-level report. It is not imported by the active signal scanner and does not connect to a broker.

## Automated replay verification

- GitHub Actions run: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45256770020
- Branch commit: `8cddbef2f97516586eafa3ae6c632af61666032b`
- Result: SUCCESS.
- Compile step: PASS.
- Offline unit tests: 11/11 PASS.
- Frozen MOEX snapshot download: PASS.
- Split-adjusted replay: `REPLAY_COMPLETED`.
- Equities-only source discovery: 10 metadata leads, 0 fetch errors.
- Combined artifact: https://github.com/vkazarin763-cloud/moex-edge-fast1/actions/runs/45256770020/artifacts/14858761919

The automated run executed the repository implementation against the downloaded frozen MOEX snapshot. Its generated JSON reproduces the trade counts, validation totals and cost-scenario metrics reported above.

