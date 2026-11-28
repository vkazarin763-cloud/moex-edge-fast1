from experimental_portfolio.multi_asset_registry import (
    ASSET_CLASS_POLICY, CANDIDATES, eligibility_decision, research_capabilities,
)


def test_discovery_registry_contains_moex_stocks_and_funds_only_as_candidates():
    classes = {item["asset_class"] for item in CANDIDATES}
    assert classes == {"equity", "fund"}
    assert len([x for x in CANDIDATES if x["asset_class"] == "equity"]) >= 40
    assert len([x for x in CANDIDATES if x["asset_class"] == "fund"]) == 19
    assert all(x["discovery_only"] for x in CANDIDATES)


def test_equity_requires_account_permission_and_validated_weekly_history():
    candidate = {"symbol": "SBER@MISX", "asset_class": "equity"}
    evidence = {
        "account_buy_permission": "BUY_ALLOWED",
        "verified_account_access": True,
        "verified_at": "2026-11-28T00:00:00Z",
        "history_validated": True,
        "valid_weekly_bars": 220,
    }
    decision = eligibility_decision(candidate, evidence)
    assert decision["eligible"] is True
    assert decision["real_orders_allowed"] is False


def test_missing_or_ambiguous_evidence_fails_closed():
    candidate = {"symbol": "SBER@MISX", "asset_class": "equity"}
    decision = eligibility_decision(candidate, {})
    assert decision["eligible"] is False
    assert "ACCOUNT_BUY_PERMISSION_NOT_CONFIRMED" in decision["reasons"]
    assert "ACCOUNT_ACCESS_NOT_VERIFIED" in decision["reasons"]
    assert "MARKET_HISTORY_NOT_VALIDATED" in decision["reasons"]


def test_futures_and_bonds_are_visible_but_blocked_until_specific_models_exist():
    for asset_class in ("bond", "future", "option"):
        decision = eligibility_decision(
            {"symbol": "TEST", "asset_class": asset_class},
            {
                "account_buy_permission": "BUY_ALLOWED",
                "verified_account_access": True,
                "verified_at": "2026-11-28T00:00:00Z",
                "history_validated": True,
                "valid_weekly_bars": 300,
            },
        )
        assert decision["eligible"] is False
        assert "ASSET_CLASS_MODEL_NOT_READY" in decision["reasons"]
        assert ASSET_CLASS_POLICY[asset_class]["research_enabled"] is False


def test_capability_report_is_explicit_about_supported_asset_classes():
    caps = research_capabilities()
    assert caps["equity"]["research_enabled"] is True
    assert caps["fund"]["research_enabled"] is True
    assert caps["bond"]["research_enabled"] is False
    assert caps["future"]["research_enabled"] is False
    assert caps["option"]["research_enabled"] is False
