# Reversal strategy check — 2026-11-21 snapshot

## Hypothesis

At each completed H1 candle close, take the direction of the just-completed candle:
- up candle -> LONG;
- down candle -> SHORT;
- keep the position until the next direction change;
- on a change, close and reverse.

The position decided at candle close is applied only to the next H1 close-to-close return. This avoids using the next candle to decide the current position.

## Sample

Same archived Finam H1 snapshot and same five-session evaluation window as the preliminary report:
2026-11-13, 2026-11-16, 2026-11-17, 2026-11-18, 2026-11-19.
44 symbols; 3,696 ticker-hour observations. Weekend rows excluded. No observations whose next bar falls on/after 2026-11-20.

## Result

- Gross mean signed return per ticker-hour: **-2.70 bps**.
- Positive ticker-hour observations: **27.38%**.
- Position direction observations: 1,728 LONG; 1,968 SHORT.
- Position changes: 2,020.
- Illustrative cost: 15 bps per one-way side; a direct LONG-to-SHORT or SHORT-to-LONG reversal pays 30 bps (close + reopen). Initial entry pays 15 bps.
- Net mean signed return per ticker-hour under this cost assumption: **-18.92 bps**.
- Always-SHORT benchmark on the same intervals, gross: **+4.16 bps** per ticker-hour.

## Decision

This particular candle-color flip rule did not work on this five-session sample. It also flips frequently (2,020 changes across 3,696 observations), so even modest execution costs are damaging.

This does not test every possible reversal model. A reversal based on a separate, delayed/confirmed trend-change signal is a different hypothesis and must be evaluated independently. Do not tune a confirmation threshold on these five sessions and then present the same sessions as an unbiased test.

This is a quick rejection result, not evidence about long-run profitability. No production, live trading, Telegram, or broker code was changed.
