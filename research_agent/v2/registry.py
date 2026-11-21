"""Explicit hypothesis registry for isolated MOEX EDGE v2 research.

This registry records definitions and prerequisites; it does not approve,
backtest, select, or activate any strategy.
"""
from __future__ import annotations

V2_STRATEGY_REGISTRY = {
    "TSM_12_1": {
        "name": "Time-Series Momentum 12-1",
        "family": "trend_momentum",
        "definition": "252-session own return excluding the most recent 21 sessions",
        "direction_rule": "positive=LONG; negative=SHORT; zero=FLAT",
        "implementation": "signal_primitive",
        "required_inputs": ["completed_D1_close", "verified_price_basis"],
        "status": "PRIMITIVE_IMPLEMENTED_NOT_VALIDATED",
    },
    "CS_MOM_12_1": {
        "name": "Cross-Sectional Momentum 12-1",
        "family": "cross_sectional_momentum",
        "definition": "Rank point-in-time universe by 252-session return excluding latest 21 sessions",
        "direction_rule": "top_20_percent=LONG_CANDIDATE; bottom_20_percent=SHORT_CANDIDATE",
        "implementation": "panel_ranking_primitive",
        "required_inputs": [
            "point_in_time_universe",
            "common_completed_D1_sessions",
            "verified_price_basis",
        ],
        "status": "RANKING_PRIMITIVE_IMPLEMENTED_NOT_VALIDATED",
    },
    "HIGH_52W": {
        "name": "52-Week High Momentum",
        "family": "price_momentum",
        "definition": "Close divided by rolling 252-session high",
        "direction_rule": "ranking_cutoffs_not_yet_frozen",
        "implementation": "metric_primitive",
        "required_inputs": ["completed_D1_high_close", "verified_price_basis"],
        "status": "METRIC_IMPLEMENTED_RULE_INCOMPLETE",
    },
    "RS_VS_IMOEX_6M_1M": {
        "name": "Relative Strength vs IMOEX",
        "family": "relative_strength",
        "definition": "Security 126-session return minus IMOEX return, skipping latest 21 sessions",
        "direction_rule": "ranking_cutoffs_not_yet_frozen",
        "implementation": "metric_primitive",
        "required_inputs": [
            "completed_D1_security",
            "completed_D1_IMOEX",
            "exact_common_anchor_sessions",
            "verified_price_basis",
        ],
        "status": "METRIC_IMPLEMENTED_RULE_INCOMPLETE",
    },
    "PAIRS_STAT_ARB": {
        "name": "Pairs Trading / Statistical Arbitrage",
        "family": "mean_reversion",
        "definition": "Pair spread mean reversion after stable relationship and hedge-ratio tests",
        "direction_rule": "not_defined",
        "implementation": "not_implemented",
        "required_inputs": [
            "corporate_action_adjusted_prices",
            "point_in_time_pair_universe",
            "liquidity_and_spread_data",
            "shortability_confirmation",
            "borrow_costs_if_applicable",
        ],
        "status": "BLOCKED_MISSING_DATA_AND_RULES",
    },
}


def get_v2_strategy_registry() -> dict:
    """Return a defensive copy of the static research hypothesis registry."""
    return {
        key: {
            **value,
            "required_inputs": list(value["required_inputs"]),
        }
        for key, value in V2_STRATEGY_REGISTRY.items()
    }
