# MOEX EDGE research protocol — 2026-11-22

## Scope
- Dataset: frozen MOEX ISS native TQBR D1 artifact run 44933369191.
- Universe: the validated 44-symbol universe.
- Final holdout starts 2026-11-20 and remains sealed and unused.
- Research is pre-holdout discovery only; no production or broker actions.

## Walk-forward
- Formation cutoffs: 20% and 55% of the shared exchange calendar.
- Validation width: 35% for each fold; validation windows must not overlap.
- Candidate generation and optimization occur independently inside each formation prefix.
- P-values from both folds and all symbols are pooled into one Holm family for this run.
- Exact cross-fold recurrence requires identical symbol, direction, entry/exit combinations, and all rule values. No fuzzy threshold matching.

## Interpretation limits
- Formation prefixes overlap; repeated discoveries are not independent confirmation.
- Holm family is limited to this run. Earlier exploratory runs (including run 38 and prior runs) are not included in the family-wise correction.
- Bootstrap block-length and transaction-cost sensitivity are not part of this run.
- A successful run or repeated candidate does not approve a strategy.
- H1 confirmation remains a separate future task.

## Frozen execution assumptions
- Use existing research simulator assumptions without tuning.
- Do not change candidate parameters after seeing validation outcomes.
- Do not use the sealed final holdout.
