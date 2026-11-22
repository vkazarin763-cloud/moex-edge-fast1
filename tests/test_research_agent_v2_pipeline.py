import unittest

from research_agent.v2.pipeline import PipelineInputError, run_research_pipeline


def make_bars(count=80):
    rows = []
    for i in range(count):
        price = 100.0 + (i % 7) * 0.2
        rows.append({
            "timestamp": f"2025-01-{1 + i // 24:02d}T{(i % 24):02d}:00:00",
            "open": price,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price + 0.1,
            "volume": 1000 + i,
        })
    return rows


def panel(count=80):
    return {
        "feature_a": [float(i % 13) for i in range(count)],
        "feature_b": [float((i * 3) % 17) for i in range(count)],
        "exit_flag": [1.0 if i % 3 == 2 else 0.0 for i in range(count)],
    }


EXIT = {"conditions": [{"feature": "exit_flag", "operator": ">=", "threshold": 1.0}]}


class ResearchPipelineTests(unittest.TestCase):
    def run_pipeline(self, data=None):
        return run_research_pipeline(
            make_bars(), data or panel(), EXIT,
            formation_end=40, max_features=2, max_hypotheses=8,
            min_formation_observations=20, min_trades_for_inference=20,
            block_length=5, resamples=999, commission_rate=0, slippage_rate=0,
            family_id="unit-test-family",
        )

    def test_validation_mutation_cannot_change_discovered_rules(self):
        original = panel()
        changed = panel()
        changed["feature_a"][40:] = [1_000_000.0] * 40
        changed["feature_b"][40:] = [-1_000_000.0] * 40
        first = self.run_pipeline(original)
        second = self.run_pipeline(changed)
        self.assertEqual(
            first["discovery"]["hypotheses"],
            second["discovery"]["hypotheses"],
        )
        self.assertEqual(first["discovery"]["feature_thresholds"],
                         second["discovery"]["feature_thresholds"])
        self.assertEqual(first["optimization"], second["optimization"])

    def test_validation_is_separate_and_family_includes_all_candidates(self):
        result = self.run_pipeline()
        self.assertEqual(result["split"]["validation_start_index"], 40)
        self.assertEqual(result["split"]["validation_bars"], 40)
        self.assertFalse(result["safety"]["trades_crossing_formation_validation_boundary"])
        self.assertEqual(
            result["family"]["family_size_generated"],
            result["family"]["family_size_corrected"],
        )
        self.assertEqual(len(result["results"]), result["family"]["family_size_generated"])
        self.assertTrue(all(row["approval_status"] == "NOT_APPROVED" for row in result["results"]))

    def test_underpowered_candidates_are_not_promoted(self):
        result = run_research_pipeline(
            make_bars(), panel(), EXIT, formation_end=40,
            max_features=2, max_hypotheses=4, min_formation_observations=20,
            min_trades_for_inference=1000, block_length=5, resamples=999,
        )
        self.assertGreater(result["summary"]["underpowered_candidates"], 0)
        self.assertTrue(all(not row["candidate_for_walk_forward"] for row in result["results"]))
        self.assertTrue(all(row["inference"] is None for row in result["results"]))


    def test_autonomous_exits_are_generated_before_validation_and_join_global_family(self):
        data = panel()
        data["extra_exit_feature"] = [float((i * 5) % 19) for i in range(80)]
        result = run_research_pipeline(
            make_bars(), data, {"mode": "AUTONOMOUS", "max_exit_hypotheses": 2},
            formation_end=40, max_features=2, max_hypotheses=8,
            min_formation_observations=20, min_trades_for_inference=1000,
            block_length=5, resamples=999, commission_rate=0, slippage_rate=0,
            family_id="autonomous-exit-test",
        )
        self.assertTrue(result["protocol"]["exit_rules_generated_from_formation_only"])
        self.assertFalse(result["protocol"]["exit_generation_uses_validation"])
        self.assertEqual(len(result["results"]), result["family"]["family_size_generated"])
        self.assertTrue(all(row["exit_hypothesis"]["role"] == "EXIT"
                            for row in result["results"]))
        self.assertEqual(len({row["candidate_id"] for row in result["results"]}),
                         len(result["results"]))
        self.assertTrue(all(row["inference"] is None for row in result["results"]))


    def test_optimizer_freezes_a_balanced_shortlist_before_validation(self):
        result = run_research_pipeline(
            make_bars(), panel(),
            {"mode": "AUTONOMOUS", "max_exit_hypotheses": 2},
            formation_end=40, max_features=2, max_hypotheses=40,
            max_optimized_candidates_per_direction=4,
            min_formation_observations=20, min_trades_for_inference=1000,
            block_length=5, resamples=999, commission_rate=0, slippage_rate=0,
            family_id="optimizer-shortlist-test",
        )
        self.assertTrue(result["optimization"]["formation_returns_used_for_optimization"])
        self.assertFalse(result["optimization"]["validation_returns_used_for_optimization"])
        self.assertLessEqual(result["optimization"]["selected_pairs"], 8)
        self.assertLessEqual(result["optimization"]["selected_by_direction"]["LONG"], 4)
        self.assertLessEqual(result["optimization"]["selected_by_direction"]["SHORT"], 4)
        logic_counts = result["optimization"]["selected_by_direction_and_logic"]
        self.assertGreater(logic_counts["LONG_ANY"], 0)
        self.assertGreater(logic_counts["SHORT_ANY"], 0)
        self.assertGreater(logic_counts["LONG_ALL"], 0)
        self.assertGreater(logic_counts["SHORT_ALL"], 0)
        exit_counts = result["optimization"]["selected_by_direction_entry_exit_logic"]
        for key in ("LONG_ALL_ALL", "LONG_ALL_ANY", "LONG_ANY_ALL", "LONG_ANY_ANY",
                    "SHORT_ALL_ALL", "SHORT_ALL_ANY", "SHORT_ANY_ALL", "SHORT_ANY_ANY"):
            self.assertGreater(exit_counts[key], 0, key)
        self.assertTrue(result["protocol"]["validation_used_for_statistical_evaluation_only"])

    def test_rejects_invalid_split_and_unaligned_features(self):
        with self.assertRaises(PipelineInputError):
            run_research_pipeline(make_bars(), panel(), EXIT, formation_end=1)
        bad = panel()
        bad["feature_a"] = bad["feature_a"][:-1]
        with self.assertRaises(PipelineInputError):
            run_research_pipeline(make_bars(), bad, EXIT, formation_end=40)


if __name__ == "__main__":
    unittest.main()
