# MOEX EDGE — Target System Blueprint

**Status:** target architecture / development contract  
**Scope:** Draft PR work only; no production deployment or broker execution.

## Product objective

Build one integrated, read-only MOEX market-analysis system for the frozen 44-stock IMOEX universe. The system collects and validates market data, generates deterministic technical candidates, estimates three-class directional probabilities, checks candidates with independent AI agents, and publishes concise, auditable signal cards. It must be useful without continuous manual operation.

This document describes the intended complete system. It does not claim that every component is implemented or that any strategy is profitable.

## Non-negotiable output contract

For every ticker and each forecast horizon, report:

- `UP`: probability of an upward move;
- `SIDEWAYS`: probability of a neutral/range-bound move;
- `DOWN`: probability of a downward move.

Horizons are **1, 5, and 20 completed MOEX trading sessions**. The three probabilities for each horizon must be finite, lie in [0, 1], and sum to 1 within a documented numeric tolerance. The dominant class is the model's direction, not a guarantee.

Every probability must carry its model version, data as-of timestamp, training/evaluation status, calibration status, and horizon. Do not display uncalibrated model output as a reliable real-world probability. Until calibration and out-of-sample checks pass, label it experimental / not calibrated.

A signal card should include ticker, dominant direction, UP/SIDEWAYS/DOWN percentages for all three horizons, D1 candidate strategy, signal-bar close and timestamp, H1 alignment, data freshness/quality, AI-agent verdicts and disagreements, model/calibration status, and explicit invalidation conditions. If no candidate passes required checks, report no signal rather than inventing one.

## System components

1. **Universe and market-data ingestion**
   - Fixed 44-symbol IMOEX universe.
   - Finam is the primary native D1/H1 market-data source for the current development path.
   - Keep data-source adapters separate so a source failure cannot silently contaminate another source's result.
   - Validate timestamps, completed-bar boundaries, OHLC relationships, duplicates, gaps, session dates, volume, and symbol coverage.
   - Retain source, retrieval time, exchange-time interpretation, and dataset hashes in the audit output.

2. **Deterministic analysis**
   - Preserve the five frozen core strategy formulas and their existing contract.
   - Keep expanded strategy hypotheses and candle/level research isolated from the frozen core until independently evaluated.
   - Generate D1 candidates and H1 confirmation from completed bars only.
   - Record conflicting strategies and directions; do not silently suppress disagreements.

3. **Three-class probability engine**
   - Predict DOWN / SIDEWAYS / UP for 1, 5, and 20 MOEX sessions.
   - Use chronological walk-forward evaluation with label-maturity embargo and no look-ahead.
   - Compare against simple baselines; report accuracy, balanced accuracy, log-loss, Brier score, class prevalence, and calibration diagnostics.
   - Probability calibration is a separate, evidence-based stage. Do not tune on the frozen holdout.

4. **Independent AI-agent review**
   - Use multiple independent roles: candidate discovery, independent verification, and adversarial critique.
   - Agents receive the same bounded, timestamped deterministic snapshot and source evidence.
   - Agents may explain, challenge, or reject a candidate; they must not invent prices, indicators, backtest metrics, or alter the model's numeric probabilities.
   - Store raw sanitized proposals, provider/model identifiers, errors, verifier decisions, and consensus rationale.
   - Agent consensus is not a substitute for statistical validation.

5. **Signal decision and presentation**
   - Combine deterministic candidate status, H1 alignment, probability output, data-quality gates, and agent review under explicit versioned rules.
   - Distinguish CONFIRMED, WATCH / INCOMPLETE, and REJECTED / NO SIGNAL states.
   - Do not force a LONG or SHORT when SIDEWAYS dominates or evidence conflicts.
   - Publish an auditable signal card and a clear no-signal result when appropriate.

6. **Automation and operations**
   - Run on a schedule aligned with completed MOEX bars and provide a manual diagnostic run.
   - Separate collection, validation, forecasting, deterministic scan, agent review, and report publication into observable stages.
   - Add bounded retries, timeouts, rate-limit handling, idempotent artifacts, sanitized logs, and clear failure states.
   - Start with free infrastructure. Consider paid speed/services only after a measurable benefit is demonstrated.
   - Delivery channel and notification cadence must be configured explicitly; do not assume a broker integration.

## Build-before-tune principle

The first objective is to assemble the complete end-to-end system with all required interfaces and safety gates. Do not spend cycles repeatedly optimizing isolated strategies while major system components remain disconnected.

The assembly gate is an end-to-end, reproducible run proving that:
- all 44 symbols have an explicit coverage outcome;
- D1 and H1 data are validated and only completed bars are used;
- the 1/5/20-session probability output has the required three classes and normalized probabilities, or reports an explicit insufficient-data state;
- frozen and exploratory strategies remain separated;
- independent agents receive the same deterministic snapshot and cannot modify model probabilities;
- conflicts, missing data, provider failures, and no-signal cases are represented;
- the full report and audit artifacts are saved;
- no broker account, order, position, or execution endpoint is accessed.

Only after that assembly gate passes should we tune strategy parameters, model choice, probability calibration, H1 filters, agent prompts/models, thresholds, and operating cadence. Every tuning decision must use development data and chronological validation. The frozen holdout beginning **2026-11-20** remains untouched for training, tuning, model selection, and performance claims.

## Safety and evidence policy

- Read-only market data only. No broker accounts, orders, positions, or execution.
- No capital allocation, position sizing, or portfolio recommendations unless separately requested.
- No invented market data, forecasts, or test metrics.
- Historical pooled trade statistics are not portfolio returns and do not prove future profitability.
- Keep changes in the development repository and Draft PR. Do not merge or modify production without separate explicit authorization.
