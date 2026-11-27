# MOEX Options Strategy Shortlist — 2026-11-27

## Decision

**No strategy is approved for live trading.** The current historical sample is useful for narrowing research, but it does not establish executable profitability.

The fastest defensible path is to retain one narrow candidate for further study and reject the rest of the current grid as unproven. Do not expand the parameter sweep.

## Dataset and coverage

Source: GitHub Actions artifact from expanded Finam options history/grid run `45934108058` (artifact `15169877937`).

- 54 option contracts were collected across SBER, GAZP, LKOH, ROSN and MOEX.
- 8,316 instrument/strategy runs and 3,780 parameter groups were evaluated.
- 93 groups met the configured minimum-count qualification thresholds.
- Contracts with at least 30 M5 bars: 12/54; H1: 11/54.
- D1 contracts with at least 20 bars: 13/54.
- Median valid history was only 7 M5, 6 H1 and 4 D1 bars per contract.

The coverage is too sparse for a broad, stable cross-market conclusion.

## What rose to the top

All 50 entries in the artifact's top-50 ranking were **GAZP PUT**, expiry 2026-12-16, M5. No CALL setup appeared in that top-50 list. This is a concentration warning, not broad confirmation.

The strongest simple candidate in that ranking:

- Underlying: GAZP
- Option: PUT, expiry 2026-12-16
- Signal: 5-bar breakout (`break5`)
- Maximum hold: 6 M5 bars
- Stop / target: 50% / 50% of option-bar price move
- Assumed round-trip cost sensitivity: 2%

| Segment | Trades | Win rate | Mean net return/trade | Median |
|---|---:|---:|---:|---:|
| Development | 25 | 48.0% | +1.03% | -0.73% |
| Chronological test | 11 | 72.7% | +4.00% | +4.45% |
| Full sample | 36 | 55.6% | +1.94% | +3.89% |

The chronological test has only 11 trades and is explicitly classified as insufficient. The development median is negative.

### Cost sensitivity

For the same rule and stop/target settings:

| Assumed cost | Development mean | Test mean | Full-sample mean |
|---|---:|---:|---:|
| 2% | +1.03% | +4.00% | +1.94% |
| 5% | -1.97% | +1.00% | -1.06% |
| 10% | -6.97% | -4.00% | -6.06% |

At 5% assumed costs, the full-sample mean turns negative. These are hypothetical cost deductions, not measured commissions or bid/ask execution costs.

## Why this is not a profitability result

1. Historical option OHLC bars are transaction/bar prices, not executable bid/ask quotes.
2. The 2%, 5% and 10% cost values are sensitivity assumptions, not measured trading costs.
3. Only 11 trades appear in the chronological test for the leading candidate.
4. The parameter grid creates selection/overfit risk; the top-ranked result was selected after many combinations.
5. The current contract sample can have survivorship and moneyness-selection bias.
6. Stop/target conflicts within a bar are resolved pessimistically (stop first), but actual fills, gaps, queue position and liquidity are not modeled.
7. No historical bid/ask replay is available for this dataset.

## Research decision

- **Keep as a research hypothesis only:** GAZP PUT M5 break5, hold 6, stop 50%, target 50%.
- **Do not activate CALL or PUT signals:** no candidate in this ranking has enough executable evidence.
- **Do not trade this candidate:** 11 test trades and OHLC-only pricing are insufficient.
- **Stop broad grid expansion:** it is not reducing uncertainty efficiently.

## One next step — not another diagnostics cycle

If research continues, collect a small, deliberately selected sample of fresh option bid/ask and order-book observations for the candidate and a comparable CALL control during active market hours. Use those observations only to establish whether spreads and quote freshness make execution plausible. A short forward archive cannot by itself prove historical profitability; it only tests market-data quality and current tradability.

No real orders, no paid services, and no production/live-mode changes are part of this research.
