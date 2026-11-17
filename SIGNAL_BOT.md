# MOEX EDGE Signal Bot

## Purpose
Separate, read-only Telegram signal notifier built on the existing MOEX EDGE FAST scanner and AI Virtual Agent strategy weights.

## Safety boundary
- Does not import or call Finam Executor.
- Does not send broker orders or modify real positions.
- Does not call or modify AI Virtual Agent portfolio logic.
- Reads `ai_weights.json`; never writes `ai_weights.json` or `ai_portfolio.json`.
- Does not calculate capital allocation, position size, stop loss, or take profit.
- Uses the existing 44-ticker scanner universe and its minimum strategy-priority gate (7).

## Signal logic
1. Fetch D1 candles from MOEX ISS and discard the current Moscow calendar day's unfinished candle.
2. Validate OHLCV, remove duplicate timestamps and invalid rows.
3. Use the existing scanner indicator and signal functions.
4. Rank eligible strategies by existing scanner priority, then AI Trainer weight.
5. Fetch H1 candles and discard any candle whose full hour has not elapsed.
6. H1 confirmation: LONG close above EMA20; SHORT close below EMA20.
7. Send a Telegram alert for a new D1 signal, and one follow-up if H1 changes from unconfirmed to confirmed. Suppress repeats thereafter.

## Schedule
GitHub Actions schedule: hourly at minute 15 during configured weekday/weekend UTC windows. Manual dispatch is also available. GitHub scheduled workflows are best-effort and can be delayed.

## Required GitHub Actions secrets
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The existing AI Agent workflow uses these same secret names. Secrets are never stored in source code.

## Files
- `signal_bot.py`: read-only scanner and Telegram delivery.
- `signal_bot_state.json`: deduplication state.
- `signal_bot_log.csv`: append-only scan/signal log.
- `.github/workflows/moex-edge-signal-bot.yml`: independent schedule.

## Limitations
The bot reports indicator-based signals, not guaranteed fills or investment advice. It has not been live-validated until the workflow completes successfully and a Telegram delivery is confirmed.
