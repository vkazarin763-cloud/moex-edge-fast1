import unittest

from research_agent.v2.archetypes import generate_archetype_hypotheses, ArchetypeInputError


def make_panel(n=80):
    return {
        "return_1": [((i * 7) % 23 - 11) / 100 for i in range(n)],
        "return_5": [((i * 5) % 19 - 9) / 100 for i in range(n)],
        "return_20": [((i * 3) % 17 - 8) / 100 for i in range(n)],
        "trend_efficiency": [(i % 10) / 10 for i in range(n)],
        "xs_relative_return_20": [((i * 11) % 29 - 14) / 100 for i in range(n)],
        "range_vs_prior_mean": [0.5 + (i % 13) / 10 for i in range(n)],
        "candle_range_pct": [0.01 + (i % 7) / 100 for i in range(n)],
        "relative_volume": [0.5 + (i % 9) / 5 for i in range(n)],
        "close_location": [(i % 10) / 10 for i in range(n)],
        "lower_wick_fraction": [(i % 6) / 10 for i in range(n)],
        "upper_wick_fraction": [(i % 5) / 10 for i in range(n)],
        "realized_volatility": [0.01 + (i % 8) / 100 for i in range(n)],
        "market_dispersion_20": [0.01 + (i % 4) / 100 for i in range(n)],
        "market_median_return_20": [((i * 3) % 11 - 5) / 100 for i in range(n)],
        "market_breadth_positive_20": [(i % 10) / 10 for i in range(n)],
    }


class ArchetypeDiscoveryTests(unittest.TestCase):
    def test_generates_multiple_archetypes_and_both_directions_and_logic(self):
        result = generate_archetype_hypotheses(
            make_panel(), formation_indices=list(range(50)),
            max_hypotheses=60, min_observations=20,
        )
        self.assertEqual(result["status"], "GENERATED")
        self.assertLessEqual(result["hypothesis_count"], 60)
        self.assertGreaterEqual(len(result["eligible_archetypes"]), 5)
        self.assertTrue(any(x["direction"] == "LONG" for x in result["hypotheses"]))
        self.assertTrue(any(x["direction"] == "SHORT" for x in result["hypotheses"]))
        self.assertTrue(any(x["combination"] == "ALL" for x in result["hypotheses"]))
        self.assertTrue(any(x["combination"] == "ANY" for x in result["hypotheses"]))
        self.assertTrue(all(x["archetype"] for x in result["hypotheses"]))

    def test_validation_tail_cannot_change_formation_thresholds_or_rules(self):
        original = make_panel()
        changed = make_panel()
        for values in changed.values():
            values[50:] = [999999.0] * 30
        kwargs = {"formation_indices": list(range(50)), "max_hypotheses": 40}
        first = generate_archetype_hypotheses(original, **kwargs)
        second = generate_archetype_hypotheses(changed, **kwargs)
        self.assertEqual(first["hypotheses"], second["hypotheses"])

    def test_candidate_cap_is_respected(self):
        result = generate_archetype_hypotheses(
            make_panel(), formation_indices=list(range(50)), max_hypotheses=7,
        )
        self.assertEqual(result["hypothesis_count"], 7)

    def test_rejects_duplicate_or_invalid_formation_indices(self):
        with self.assertRaises(ArchetypeInputError):
            generate_archetype_hypotheses(
                make_panel(), formation_indices=[0, 1, 1, 2],
            )


if __name__ == "__main__":
    unittest.main()
