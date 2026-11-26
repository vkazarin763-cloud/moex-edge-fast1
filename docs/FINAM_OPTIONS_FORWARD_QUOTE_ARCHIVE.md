# Finam forward option quote archive (research only)

Status: implementation prepared on an isolated Draft PR branch. No production workflow, default branch, Telegram, scheduler, account, or order path is changed.

## Purpose

Collect a forward time series of current bid/ask quote and order-book snapshots for:

- GAZP PUT: `GZ100CX6@RTSX`
- SBER PUT: `SR290CX6@RTSX`

The collector requests only:

- `GET /v1/instruments/{symbol}/quotes/latest`
- `GET /v1/instruments/{symbol}/orderbook`

It authenticates using the already configured `FINAM_API_SECRET`. It never calls account, portfolio, order, cancel, or SL/TP endpoints. It never writes the secret or JWT to the artifact.

## Bounded run

GitHub Actions workflow input defaults to 60 minutes and 15-second polling; duration is capped at 240 minutes, polling at 10–60 seconds, and at most four symbols are accepted. Output is a JSON Lines artifact retained for 30 days.

This is a forward archive, not a reconstruction of past order books. It records observation time, quote timestamp, best bid/ask, displayed sizes, spread, and raw returned order-book levels. A displayed quote is not a guaranteed fill.

## Important GitHub Actions constraint

The workflow uses `workflow_dispatch`. GitHub only offers manual dispatch for workflow files present on the repository's default branch. This PR is deliberately Draft and must remain unmerged, so the Run workflow button will not be available until the workflow is deliberately merged to the default branch. A push-trigger workaround was intentionally avoided because it would start collection immediately, possibly outside the MOEX trading session.

No run has been started by this change. After a deliberate merge, run it manually during the MOEX session; begin with 60 minutes. Do not schedule continuous capture or activate trading from this research alone.

## Interpretation

A useful sample should show repeated fresh quote timestamps, non-crossed positive bid/ask, stable or improving spread, and meaningful displayed depth during active market hours. It still cannot prove queue position or actual fill probability. The resulting archive can support a later conservative forward replay using ask for hypothetical buys and bid for hypothetical exits, with fees and slippage assumptions stated separately.
