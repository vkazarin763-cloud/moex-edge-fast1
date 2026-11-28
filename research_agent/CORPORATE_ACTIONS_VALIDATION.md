# Corporate-action and fund-distribution validation

Status: research-only. No price adjustment or deposit comparison is enabled.

## Equity dividends

Finam `/v1/past-dividends` returns a `date` described as the register closing date. Do not interpret it as the last-buy/ex-date. Preserve the vendor event unchanged and reconcile issuer, amount, currency, record date, ex/last-buy date, and payment date before using it in a total-return series.

MOEX's published rule for its equity total-return indices is to account for dividends on the trading day that is the record date; if the record date is not a trading day, use the preceding trading day. This is a benchmark methodology, not permission to silently transform incomplete vendor events.

Source: https://www.moex.com/n63176

## Fund distributions

Do not use Finam `/v1/past-dividends` as a completeness test for a fund's distributions. The endpoint's successful empty response only means that this endpoint returned no events for that fund instrument; it does not prove that the fund made no distributions. It may also describe dividends paid by securities held inside a fund, which is a different event layer from cash paid by the fund to unitholders.

Use the Bank of Russia mutual-fund data showcase as the primary discovery/coverage source. The regulator states that its monthly workbook is compiled from fund management rules and reporting and includes:
- management company and fund characteristics;
- whether income from trust management is payable to unitholders;
- payment frequency;
- a link to the management company's disclosure site.

The page was updated 2026-11-10. Join fund records by ISIN (not ticker alone), then verify the current management rules and actual payment notices on the manager's official disclosure site. The regulator's workbook is a discovery/coverage source; the management rules and payment notices remain the evidence for an individual event.

Source: https://www.cbr.ru/RSCI/data_showcase/
Workbook: https://www.cbr.ru/Content/Document/File/193443/mutual_fund_data.xlsx

## Required statuses

- `DISTRIBUTION_RIGHT_YES`: regulator workbook says payments are provided; obtain manager's payment history and reconcile actual amount/date.
- `DISTRIBUTION_RIGHT_NO`: regulator workbook says no regular payments; fund income is generally reflected in NAV, subject to the fund rules.
- `DISTRIBUTION_RIGHT_UNKNOWN`: missing, ambiguous, stale, or unmatched record; do not infer no payments.
- `PAYMENT_HISTORY_VERIFIED`: actual manager disclosures reconciled for the requested period.
- `PAYMENT_HISTORY_INCOMPLETE`: only partial or no event history found; total-return comparison remains blocked.

## Safety gate

Until every fund has an ISIN-matched distribution-right status and any required payment history is reconciled, keep fund total-return adjustment and deposit comparison as `NOT_COMPARABLE`. Never treat an empty Finam response as evidence of no distribution. Do not bypass TLS or use guessed dates/amounts.
