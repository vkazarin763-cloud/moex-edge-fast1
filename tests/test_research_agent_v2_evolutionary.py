import unittest

from research_agent.v2.evolutionary import expand_hypotheses


class EvolutionaryDiscoveryTests(unittest.TestCase):
    def panel(self):
        return {
            f"feature_{i}": [float((row * (i + 3)) % 97) for row in range(80)]
            for i in range(8)
        }

    def seeds(self):
        return [
            {"id": "seed-long", "direction": "LONG", "conditions": [
                {"feature": "feature_0", "operator": ">=", "threshold": 20.0}]},
            {"id": "seed-short", "direction": "SHORT", "conditions": [
                {"feature": "feature_1", "operator": "<=", "threshold": 60.0},
                {"feature": "feature_2", "operator": ">=", "threshold": 30.0}]},
        ]

    def test_generates_three_and_four_condition_rules_deterministically(self):
        result = expand_hypotheses(
            self.panel(), formation_indices=list(range(60)),
            seed_hypotheses=self.seeds(), max_hypotheses=100,
        )
        self.assertGreater(result["hypothesis_count"], 0)
        self.assertTrue(all(3 <= len(item["conditions"]) <= 4
                            for item in result["hypotheses"]))
        self.assertEqual({item["direction"] for item in result["hypotheses"]},
                         {"LONG", "SHORT"})
        self.assertEqual({item["combination"] for item in result["hypotheses"]},
                         {"ALL", "ANY"})
        for key in ("LONG_ALL", "LONG_ANY", "SHORT_ALL", "SHORT_ANY"):
            self.assertGreater(result["selected_by_direction_and_logic"][key], 0)
        again = expand_hypotheses(
            self.panel(), formation_indices=list(range(60)),
            seed_hypotheses=self.seeds(), max_hypotheses=100,
        )
        self.assertEqual(result, again)

    def test_mutation_thresholds_ignore_validation_rows(self):
        first = self.panel()
        changed = {name: list(values) for name, values in first.items()}
        for values in changed.values():
            values[60:] = [1e12] * 20
        args = {"formation_indices": list(range(60)),
                "seed_hypotheses": self.seeds(), "max_hypotheses": 100}
        a = expand_hypotheses(first, **args)
        b = expand_hypotheses(changed, **args)
        self.assertEqual(a["hypotheses"], b["hypotheses"])
        self.assertFalse(a["safety"]["validation_rows_used"])

    def test_candidate_cap_is_respected(self):
        result = expand_hypotheses(
            self.panel(), formation_indices=list(range(60)),
            seed_hypotheses=self.seeds(), max_hypotheses=7,
        )
        self.assertEqual(result["hypothesis_count"], 7)


if __name__ == "__main__":
    unittest.main()
