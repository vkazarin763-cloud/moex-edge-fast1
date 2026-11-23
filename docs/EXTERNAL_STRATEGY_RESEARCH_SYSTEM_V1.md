# External Strategy Research System — Design v1

## Purpose

Replace the current AI strategy-scout limitation (five preselected stock strategies) with a provenance-first pipeline that discovers documented strategies from public sources, extracts exact rules, adapts them to MOEX instruments, and submits them to independent deterministic validation.

This is a design contract, not a claim that discovery, backtests, or signals are implemented.

## Markets and boundaries

1. Equities — preserve the current frozen 44-stock universe.
2. Futures — MOEX FORTS contracts, with contract identity, expiry/roll, multiplier, tick size/value, sessions, liquidity, margin and continuous-series construction explicitly represented.
3. Options — a separate options research/scanner path. Preserve the existing MOEX OPTIONS SIGNAL BOT as a distinct product; do not merge its bot, state, or delivery channel into the stock/futures scanner. Performance testing requires actual historical option-chain/quote data (bid/ask, strikes, expiries, OI/volume, underlying and timestamps). Black–Scholes-only synthetic premiums are not historical option backtests.

No broker order placement, execution, account mutation, position sizing, or capital allocation is part of this research system. Existing execution workflows and the production repository are out of scope.

## Pipeline

Source discovery -> source screening -> rule extraction -> instrument adapter -> data readiness -> deterministic implementation -> independent validation -> research registry -> signal scanner.

### 1. Source discovery

Search public sources, prioritizing peer-reviewed papers, working papers, technical reports, public GitHub repositories/notebooks, documented systematic strategies, and detailed practitioner articles with exact reproducible rules.

Use free/public sources and existing free-tier AI providers first. AI may summarize/classify sources, but must preserve URLs and evidence locations. Search results and promotional claims are leads, not proof.

### 2. Provenance and licensing

Every candidate stores a stable ID, normalized name, source URL/title/author/publication date/retrieval date, source type, original market/instrument, exact extracted rules and evidence locations, license/copyright status, assumptions, limitations, evidence quality, and content hash/version.

Do not copy source code unless its license permits it. Reject or quarantine unverifiable provenance, missing rule details, incompatible licensing for copied code, or claims that cannot be independently inspected.

### 3. Rule extraction

Represent strategies as declarative, versioned rules rather than executable LLM-generated Python. Record entry, direction, signal timing, exits, timeframe, indicator definitions, required data/warm-up, execution assumptions, costs, and original market assumptions.

Unknown or ambiguous rules remain INCOMPLETE; agents must not fill gaps by guessing.

### 4. Instrument-specific adapters

Equities: corporate actions, suspensions, sessions, liquidity and short-sale constraints where relevant.

Futures: expiry/roll, multiplier, tick size/value, basis, session calendar, liquidity, margin and continuous-contract adjustment policy.

Options: option-chain identity, strike/expiry, exercise/settlement style, multiplier, bid/ask, OI/volume, IV surface, Greeks, theta decay, spread and assignment/settlement mechanics.

A candidate can be NOT_ADAPTABLE or DATA_NOT_READY; it must not silently substitute synthetic data.

### 5. Independent deterministic validation

LLM agents do not run or certify the authoritative backtest. A separate deterministic engine validates raw data, timestamps, duplicates, gaps, OHLC and completed-bar boundaries; uses chronological train/validation/holdout and walk-forward evaluation; prevents lookahead/survivorship/corporate-action leakage; models instrument-specific costs, spreads, slippage, rolls and expiry; reports metrics only when actually calculated; and fails closed on insufficient data or malformed rules.

The validator must be independent of the discovering/extracting agent. No candidate is promoted based solely on in-sample results or an author's claimed profitability.

### 6. Registry states

Lifecycle: DISCOVERED -> SOURCE_REVIEWED -> EXTRACTED -> ADAPTABLE -> DATA_READY -> IMPLEMENTED -> TESTING -> EXPERIMENTAL.

Other states: REJECTED, INCOMPLETE, NOT_ADAPTABLE, DATA_NOT_READY, VALIDATION_FAILED.

Explicit research approval is required before a candidate enters a signal-eligible registry. Approval is not a guarantee of future profitability and is not permission to trade.

## Agent roles

Start with a small team: (1) Research scout discovers sources and records provenance; (2) Rule extractor produces structured rules and evidence; (3) Market adapter identifies requirements/data gaps and cannot approve its own work; (4) Independent verifier performs deterministic tests and adversarial review.

Research runs at low frequency or manually at first. The fast signal scan must not wait for discovery; it may use only previously approved, cached strategies.

## Delivery plan

### Phase 0 — safe smoke test

Prove the free-tier agent can discover and record a small set of public strategy sources across equities, futures and options. No market-data backtest and no signal processing. Verify provenance, duplicate handling, structured output, failure handling and runtime.

### Phase 1 — equity pilot

Select a small number of well-documented candidates; adapt and independently test on the frozen 44-stock universe. Keep candidates experimental until data-quality and validation gates pass.

### Phase 2 — futures pilot

Audit futures data/scanner first. Add contract metadata, roll-aware history and costs before testing candidates. Document continuous-series construction and its biases.

### Phase 3 — options pilot

First prove access to actual historical option-chain/quote data and validate timestamps, bid/ask, OI, volume, strikes and expiries. Until then, literature discovery is allowed, but candidates remain DATA_NOT_READY and cannot publish performance or actionable signals.

### Phase 4 — controlled signal integration

Connect only approved registry entries to the relevant market-specific scanner. Keep stock, futures and options signals, data, logs and bot delivery isolated. No auto-trading.

## First acceptance criteria

The first smoke test passes only if it uses free/public sources and the existing free-tier provider; completes without downloading/processing market candles; records source URL and provenance for every candidate; rejects/quarantines malformed, duplicate and unsupported candidates; never treats LLM output as a backtest, validation result or signal; and invokes no broker/execution workflow or production repository.