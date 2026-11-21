import unittest

from research_agent.v2.registry import get_v2_strategy_registry


class V2StrategyRegistryTests(unittest.TestCase):
    def test_registry_contains_five_research_hypotheses(self):
        registry = get_v2_strategy_registry()
        self.assertEqual(
            set(registry),
            {
                "TSM_12_1",
                "CS_MOM_12_1",
                "HIGH_52W",
                "RS_VS_IMOEX_6M_1M",
                "PAIRS_STAT_ARB",
            },
        )

    def test_registry_does_not_claim_validation_or_approval(self):
        registry = get_v2_strategy_registry()
        for entry in registry.values():
            self.assertTrue(
                any(marker in entry["status"] for marker in ("NOT_VALIDATED", "INCOMPLETE", "BLOCKED"))
            )

    def test_pairs_strategy_is_explicitly_blocked_until_data_exists(self):
        entry = get_v2_strategy_registry()["PAIRS_STAT_ARB"]
        self.assertEqual(entry["implementation"], "not_implemented")
        self.assertEqual(entry["status"], "BLOCKED_MISSING_DATA_AND_RULES")
        self.assertIn("shortability_confirmation", entry["required_inputs"])

    def test_registry_returns_defensive_copy(self):
        registry = get_v2_strategy_registry()
        registry["TSM_12_1"]["required_inputs"].append("fake")
        self.assertNotIn(
            "fake", get_v2_strategy_registry()["TSM_12_1"]["required_inputs"]
        )


if __name__ == "__main__":
    unittest.main()
