import unittest

from research_agent.v2.frozen_candidate_replay import (
    find_candidate,
    replay_frozen_candidate,
)


def make_rows(n=36):
    rows = []
    for i in range(n):
        price = 100.0 + i * 0.1
        rows.append({
            "timestamp": f"2026-01-{i + 1:02d}T00:00:00",
            "open": price,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price,
            "volume": 1000.0,
        })
    return rows


class FrozenCandidateReplayTests(unittest.TestCase):
    def test_finds_exactly_one_candidate(self):
        report = {"candidates_for_walk_forward": [{
            "symbol": "AAA", "direction": "SHORT",
            "entry_combination": "ANY", "entry_rule": [
                {"feature": "trend_efficiency", "operator": "<=", "threshold": 1.0}
            ],
            "exit_combination": "ALL", "exit_rule": [
                {"feature": "close_location", "operator": ">=", "threshold": 0.0}
            ],
        }]}
        self.assertEqual(find_candidate(report, "AAA", "SHORT")["symbol"], "AAA")

    def test_replay_uses_only_requested_window_and_keeps_holdout_closed(self):
        candidate = {
            "symbol": "AAA", "direction": "SHORT",
            "entry_combination": "ANY",
            "entry_rule": [
                {"feature": "trend_efficiency", "operator": "<=", "threshold": 1.0}
            ],
            "exit_combination": "ALL",
            "exit_rule": [
                {"feature": "close_location", "operator": ">=", "threshold": 0.0},
                {"feature": "return_20", "operator": ">=", "threshold": -1.0},
            ],
        }
        dataset = {
            "generated_at_utc": "2026-11-21T00:00:00+00:00",
            "holdout_start": "2026-11-20",
            "universe_size": 2,
            "symbols": {"AAA": make_rows(), "BBB": make_rows()},
        }
        result = replay_frozen_candidate(
            dataset, candidate,
            start_date="2026-01-22",
            end_date="2026-01-30",
        )
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["data"]["first_replay_bar"], "2026-01-22")
        self.assertEqual(result["data"]["last_replay_bar"], "2026-01-30")
        self.assertFalse(result["safety"]["rules_generated_or_optimized"])
        self.assertFalse(result["safety"]["sealed_holdout_used"])
        self.assertEqual([x["cost_multiplier"] for x in result["cost_sensitivity"]], [1, 2, 3])

    def test_rejects_window_that_touches_sealed_holdout(self):
        dataset = {
            "generated_at_utc": "2026-11-21T00:00:00+00:00",
            "holdout_start": "2026-11-20",
            "universe_size": 2,
            "symbols": {"AAA": make_rows(), "BBB": make_rows()},
        }
        candidate = {
            "symbol": "AAA", "direction": "SHORT",
            "entry_combination": "ANY",
            "entry_rule": [{"feature": "trend_efficiency", "operator": "<=", "threshold": 1.0}],
            "exit_combination": "ALL",
            "exit_rule": [{"feature": "close_location", "operator": ">=", "threshold": 0.0}],
        }
        with self.assertRaises(ValueError):
            replay_frozen_candidate(
                dataset, candidate,
                start_date="2026-01-22",
                end_date="2026-11-20",
            )


if __name__ == "__main__":
    unittest.main()
