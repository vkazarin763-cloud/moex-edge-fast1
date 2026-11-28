"""Deterministic RUB deposit hurdle snapshot for forward-looking research only."""
from __future__ import annotations

DEPOSIT_SNAPSHOT = {
    "as_of": "2026-11-27",
    "currency": "RUB",
    "source": "Bank of Russia, monitoring of maximum rates at ten largest deposit-taking banks",
    "source_url": "https://www.cbr.ru/press/pr?file=639313833655037811BANK_SECTOR.htm",
    "rates": {
        "up_to_90_days": 0.1260,
        "91_to_180_days": 0.1318,
        "181_days_to_1_year": 0.1285,
        "over_1_year": 0.1196,
    },
    "headline_rate": 0.1333,
    "tax_basis": "gross_before_personal_tax",
    "notes": (
        "Indicative maximum average rates, not guaranteed offers. Actual eligibility, "
        "amount limits, new-money conditions, capitalization, withdrawal restrictions "
        "and personal tax may change realized return."
    ),
}


def get_deposit_hurdle(term: str = "181_days_to_1_year") -> dict:
    """Return the current annualized gross hurdle for a deposit term."""
    if term not in DEPOSIT_SNAPSHOT["rates"]:
        raise ValueError(f"unknown_deposit_term:{term}")
    return {
        "as_of": DEPOSIT_SNAPSHOT["as_of"],
        "currency": DEPOSIT_SNAPSHOT["currency"],
        "term": term,
        "annual_rate": DEPOSIT_SNAPSHOT["rates"][term],
        "tax_basis": DEPOSIT_SNAPSHOT["tax_basis"],
        "source": DEPOSIT_SNAPSHOT["source"],
        "source_url": DEPOSIT_SNAPSHOT["source_url"],
        "notes": DEPOSIT_SNAPSHOT["notes"],
    }


def compare_to_deposit(
    strategy_metrics: dict,
    term: str = "181_days_to_1_year",
    required_excess_rate: float = 0.0,
) -> dict:
    """Compare annualized strategy CAGR with a current deposit hurdle.

    required_excess_rate is an explicit additional annual return premium.
    Beating this hurdle never approves a strategy for live use.
    """
    if not isinstance(required_excess_rate, (int, float)) or required_excess_rate < 0:
        raise ValueError("required_excess_rate_must_be_nonnegative")
    hurdle = get_deposit_hurdle(term)
    cagr = strategy_metrics.get("cagr")
    if not isinstance(cagr, (int, float)):
        return {"status": "NOT_COMPARABLE", "reason": "missing_cagr", "deposit_hurdle": hurdle}
    target = hurdle["annual_rate"] + required_excess_rate
    excess = float(cagr) - target
    return {
        "status": "ABOVE_HURDLE_NOT_APPROVED" if excess > 0 else "BELOW_HURDLE",
        "strategy_cagr": float(cagr),
        "deposit_hurdle_rate": hurdle["annual_rate"],
        "required_excess_rate": float(required_excess_rate),
        "total_hurdle_rate": target,
        "excess_over_hurdle": excess,
        "max_drawdown": strategy_metrics.get("max_drawdown"),
        "deposit_benchmark": hurdle,
        "warning": (
            "Research comparison only. Strategy CAGR is historical and volatile; deposit "
            "rate is a current indicative gross rate. Align periods, taxes and actual costs. "
            "Passing is never live approval."
        ),
    }
