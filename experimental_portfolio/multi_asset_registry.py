"""Fail-closed registry for the isolated multi-asset research programme.

This module discovers and classifies candidates; it does not fetch prices, size positions,
or connect to broker order endpoints. Account permission and market-data validation are
mandatory before a candidate can enter any comparative backtest.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

# Candidate symbols are discovery inputs, not claims of account availability.
MOEX_STOCKS = (
    "AFKS", "AFLT", "ALRS", "BSPB", "CBOM", "CHMF", "CNRU", "DOMRF",
    "ENPG", "FLOT", "GAZP", "GMKN", "HEAD", "IRAO", "LKOH", "MAGN",
    "MDMG", "MOEX", "MTSS", "NLMK", "NVTK", "OZON", "PHOR", "PLZL",
    "POSI", "RAGR", "RENI", "ROSN", "RTKM", "RUAL", "SBER", "SBERP",
    "SNGS", "SNGSP", "SVCB", "T", "TATN", "TATNP", "TRNFP", "UGLD",
    "VKCO", "VTBR", "X5", "YDEX",
)
MOEX_FUNDS = (
    "AKME", "AKMM", "AMNR", "AMNY", "AMRE", "AMRH", "BCSD", "DIVD",
    "EQMX", "GOLD", "LQDT", "SBCB", "SBGB", "SBMM", "SBMX", "SBRB",
    "TBRU", "TGLD", "TMOS",
)

# Stocks and exchange-traded funds can share validated weekly OHLC methodology.
# Bonds/futures/options require additional instrument-specific modeling before inclusion.
ASSET_CLASS_POLICY: dict[str, dict[str, Any]] = {
    "equity": {
        "research_enabled": True,
        "frequency": "weekly",
        "minimum_valid_bars": 200,
        "required_market_fields": (),
        "reason": "Weekly OHLC research is supported; account permission is still required.",
    },
    "fund": {
        "research_enabled": True,
        "frequency": "weekly",
        "minimum_valid_bars": 200,
        "required_market_fields": (),
        "reason": "Weekly OHLC research is supported; account permission is still required.",
    },
    "bond": {
        "research_enabled": False,
        "frequency": "weekly",
        "minimum_valid_bars": 200,
        "required_market_fields": ("maturity_date", "coupon_schedule", "nominal", "accrued_interest"),
        "reason": "Awaiting bond cash-flow, duration and redemption modeling.",
    },
    "future": {
        "research_enabled": False,
        "frequency": "weekly",
        "minimum_valid_bars": 200,
        "required_market_fields": ("expiry", "multiplier", "initial_margin", "maintenance_margin", "roll_method"),
        "reason": "Awaiting expiry, multiplier, margin, financing and continuous-roll modeling.",
    },
    "option": {
        "research_enabled": False,
        "frequency": "daily",
        "minimum_valid_bars": 200,
        "required_market_fields": ("expiry", "strike", "option_type", "multiplier", "historical_bid_ask"),
        "reason": "Awaiting contract-level bid/ask history, expiry and payoff modeling.",
    },
}

CANDIDATES = tuple(
    {"symbol": f"{symbol}@MISX", "asset_class": "equity", "market": "MOEX", "discovery_only": True}
    for symbol in MOEX_STOCKS
) + tuple(
    {"symbol": f"{symbol}@MISX", "asset_class": "fund", "market": "MOEX", "discovery_only": True}
    for symbol in MOEX_FUNDS
)


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def eligibility_decision(candidate: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Return a reasoned decision; unknown, stale or incomplete evidence always blocks."""
    asset_class = candidate.get("asset_class")
    policy = ASSET_CLASS_POLICY.get(asset_class)
    reasons: list[str] = []
    if not policy:
        reasons.append("UNKNOWN_ASSET_CLASS")
    elif not policy["research_enabled"]:
        reasons.append("ASSET_CLASS_MODEL_NOT_READY")

    if evidence.get("account_buy_permission") != "BUY_ALLOWED":
        reasons.append("ACCOUNT_BUY_PERMISSION_NOT_CONFIRMED")
    if evidence.get("verified_account_access") is not True:
        reasons.append("ACCOUNT_ACCESS_NOT_VERIFIED")
    if not _valid_timestamp(evidence.get("verified_at")):
        reasons.append("PERMISSION_TIMESTAMP_MISSING_OR_INVALID")
    if evidence.get("history_validated") is not True:
        reasons.append("MARKET_HISTORY_NOT_VALIDATED")
    if policy:
        try:
            bars = int(evidence.get("valid_weekly_bars", 0))
        except (TypeError, ValueError):
            bars = 0
        if bars < policy["minimum_valid_bars"]:
            reasons.append("INSUFFICIENT_VALID_HISTORY")
        for field in policy["required_market_fields"]:
            if evidence.get(field) in (None, "", []):
                reasons.append("MISSING_" + field.upper())

    return {
        "eligible": not reasons,
        "symbol": candidate.get("symbol"),
        "asset_class": asset_class,
        "reasons": reasons,
        "paper_only": True,
        "real_orders_allowed": False,
    }


def research_capabilities() -> dict[str, Any]:
    return {
        name: {
            "research_enabled": policy["research_enabled"],
            "frequency": policy["frequency"],
            "minimum_valid_bars": policy["minimum_valid_bars"],
            "required_market_fields": list(policy["required_market_fields"]),
            "reason": policy["reason"],
        }
        for name, policy in ASSET_CLASS_POLICY.items()
    }
