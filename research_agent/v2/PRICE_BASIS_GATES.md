# V2 price-basis gates

Cross-sectional momentum requires an explicit price-basis status for every ticker. A ticker is eligible only when its status is `verified_adjusted` or `verified_same_share`. Missing or unverified statuses exclude that ticker. The strategy also requires at least 10 verified constituents by default and 253 common completed sessions through the formation date.

Relative strength versus IMOEX requires separate verified statuses for the security and the benchmark. Exact formation, lookback-anchor and skip-anchor timestamps must match.

The caller must derive these statuses from source audits; this module does not infer them from the mere absence of a known corporate-action event. The v1 corporate-action policy's exclusion of pre-event bars is useful input, but a `NO_KNOWN_CORPORATE_ACTION` label is not automatically equivalent to verified same-share history.

No performance test should run until the source audit and point-in-time universe provenance are independently established.
