# MOEX Agent V1 — isolated paper experiment

This experiment runs the pinned upstream MOEX Agent V1 in **paper-only** mode.
It never connects to Finam, never places broker orders, and Telegram is disabled.

- Universe: the 44 configured MOEX shares.
- Directions: LONG and SHORT. The upstream model estimates probability of an upward move; the local patch converts it to probability of a downward move for SHORT.
- Execution: one pipeline cycle per GitHub Actions run; weekday hourly schedule during the configured Moscow-time session window, plus manual dispatch.
- Models: upstream pretrained artifacts pinned to commit `5b8a3e56c933a85554feb7496fb251ac95ced1a6`. Their published training metrics are not independently validated here.
- Output: GitHub Actions log and SQLite paper database artifact. No real orders or portfolio sizing.

The first successful cycle proves only that data collection and the signal pipeline execute. It does not establish profitability.
