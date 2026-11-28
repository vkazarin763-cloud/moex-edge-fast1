# Weekly Strategy Batch

Manual workflow checks account buy permission for every symbol before downloading five-year weekly history. Only instruments with at least 200 valid bars are evaluated.

Artifacts: validated bars + JSON summary and CSV strategy metrics. Artifacts expire in 90 days; data is not committed to git. No credentials/account identifiers are included.

Read-only only: no order endpoints, broker execution, or portfolio-state changes. Results are exploratory retrospective baselines; not a recommendation or forward validation.
