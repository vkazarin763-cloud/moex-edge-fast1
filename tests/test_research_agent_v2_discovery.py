import unittest

from research_agent.v2.discovery import (
    DiscoveryInputError,
    generate_hypotheses,
    matches_hypothesis,
    generate_exit_hypotheses,
)


class HypothesisDiscoveryTests(unittest.TestCase):
    def panel(self):
        return {
            "range_expansion": [float(i) for i in range(40)],
            "relative_volume": [float(40 - i) for i in range(40)],
            "market_pressure": [float(i % 7) for i in range(40)],
        }

    def test_generates_directional_combinations_without_known_strategy_names(self):
        result = generate_hypotheses(
            self.panel(), formation_indices=list(range(30)), min_observations=20
        )
        self.assertEqual(result["status"], "GENERATED")
        self.assertGreater(result["hypothesis_count"], 0)
        self.assertTrue(result["safety"]["thresholds_fit_on_formation_indices_only"])
        self.assertFalse(result["safety"]["forward_returns_used"])
        self.assertEqual(
            {item["direction"] for item in result["hypotheses"]}, {"LONG", "SHORT"}
        )
        self.assertTrue(
            all(item["id"].startswith("HYP-") for item in result["hypotheses"])
        )
        self.assertTrue(
            any(len(item["conditions"]) == 2 for item in result["hypotheses"])
        )

    def test_generation_is_deterministic(self):
        args = {"formation_indices": list(range(30)), "min_observations": 20}
        first = generate_hypotheses(self.panel(), **args)
        second = generate_hypotheses(self.panel(), **args)
        self.assertEqual(first, second)

    def test_thresholds_ignore_rows_outside_formation_window(self):
        data = {"feature": [float(i) for i in range(30)] + [1_000_000.0] * 10}
        result = generate_hypotheses(
            data, formation_indices=list(range(30)),
            quantiles=(0.5,), min_observations=20,
        )
        self.assertEqual(result["feature_thresholds"]["feature"][0]["value"], 14.5)

    def test_candidate_limit_is_enforced(self):
        result = generate_hypotheses(
            self.panel(), formation_indices=list(range(30)),
            min_observations=20, max_hypotheses=7,
        )
        self.assertEqual(result["hypothesis_count"], 7)
        self.assertTrue(result["truncated"])

    def test_missing_feature_value_fails_closed(self):
        panel = {"feature": [float(i) for i in range(25)] + [None]}
        result = generate_hypotheses(
            panel, formation_indices=list(range(25)), quantiles=(0.5,),
            min_observations=20,
        )
        hypothesis = next(
            item for item in result["hypotheses"] if item["direction"] == "LONG"
        )
        self.assertFalse(matches_hypothesis(hypothesis, panel, 25))

    def test_matching_rule_uses_all_conditions(self):
        panel = {"a": [1.0, 9.0], "b": [9.0, 1.0]}
        hypothesis = {
            "conditions": [
                {"feature": "a", "operator": ">=", "threshold": 5.0},
                {"feature": "b", "operator": "<=", "threshold": 5.0},
            ]
        }
        self.assertFalse(matches_hypothesis(hypothesis, panel, 0))
        self.assertTrue(matches_hypothesis(hypothesis, panel, 1))

    def test_rejects_misaligned_and_nonfinite_feature_series(self):
        with self.assertRaises(DiscoveryInputError):
            generate_hypotheses(
                {"a": [1.0, 2.0], "b": [1.0]},
                formation_indices=[0], min_observations=2,
            )
        with self.assertRaises(DiscoveryInputError):
            generate_hypotheses(
                {"a": [1.0, float("nan"), 2.0]},
                formation_indices=[0, 1, 2], min_observations=2,
            )


    def test_small_cap_is_balanced_across_features_and_directions(self):
        panel = {f"feature_{i:02d}": [float((j * (i + 1)) % 37) for j in range(60)]
                 for i in range(12)}
        result = generate_hypotheses(
            panel, formation_indices=list(range(45)),
            min_observations=20, max_hypotheses=20,
        )
        used = {condition["feature"] for item in result["hypotheses"]
                for condition in item["conditions"]}
        self.assertGreaterEqual(len(used), 9)
        self.assertEqual({item["direction"] for item in result["hypotheses"]},
                         {"LONG", "SHORT"})

    def test_exit_hypotheses_are_formation_only_and_rotate_away_from_entry_feature(self):
        data = self.panel()
        entry = {"id": "HYP-test", "direction": "LONG",
                 "conditions": [{"feature": "range_expansion",
                                 "operator": ">=", "threshold": 10.0}]}
        result = generate_exit_hypotheses(
            data, formation_indices=list(range(30)),
            entry_hypothesis=entry, max_exit_hypotheses=2,
        )
        self.assertEqual(result["hypothesis_count"], 2)
        self.assertTrue(all(item["conditions"][0]["feature"] != "range_expansion"
                            for item in result["hypotheses"]))
        self.assertTrue(result["safety"]["thresholds_fit_on_formation_indices_only"])
        changed = {name: list(values) for name, values in data.items()}
        for values in changed.values():
            values[30:] = [999999.0] * 10
        again = generate_exit_hypotheses(
            changed, formation_indices=list(range(30)),
            entry_hypothesis=entry, max_exit_hypotheses=2,
        )
        self.assertEqual(result["hypotheses"], again["hypotheses"])

    def test_rejects_duplicate_formation_indices(self):
        with self.assertRaises(DiscoveryInputError):
            generate_hypotheses(
                self.panel(), formation_indices=[0, 1, 1], min_observations=2
            )


if __name__ == "__main__":
    unittest.main()
