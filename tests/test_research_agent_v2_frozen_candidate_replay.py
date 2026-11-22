import unittest
from datetime import date, timedelta

from research_agent.v2.frozen_candidate_replay import (
    find_candidate,
    replay_frozen_candidate,
)


def make_rows(n=36):
    rows = []
    first = date(2026, 1, 1)
    for i in range(n):
        price = 100.0 + i * 0.1
        rows.append({
            "timestamp": f"{first + timedelta(days=i)}T00:00:00",
            "open": price,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price,
            "volume": 1000.0,
        })
    return rows


def make_candidate():
    return {
        "symbol": "AAA", "direction": "SHORT",
        "selection_cutoff_date": "2026-01-21",
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


class FrozenCandidateReplayTests(unittest.TestCase):
    def test_finds_candidate_and_selection_cutoff(self):
        candidate = make_candidate()
        candidate["fold_id"] = "fold-1"
        report = {
            "candidates_for_walk_forward": [candidate],
            "folds": [{
                "fold_id": "fold-1",
                "evaluation_cutoff_date": "2026-01-21",
            }],
        }
        found = find_candidate(report, "AAA", "SHORT")
        self.assertEqual(found["symbol"], "AAA")
        self.assertEqual(found["selection_cutoff_date"], "2026-01-21")

    def test_replay_uses_only_requested_window_and_keeps_holdout_closed(self):
        dataset = {
            "generated_at_utc": "2026-11-21T00:00:00+00:00",
            "holdout_start": "2026-11-20",
            "universe_size": 2,
            "symbols": {"AAA": make_rows(), "BBB": make_rows()},
        }
        result = replay_frozen_candidate(
            dataset, make_candidate(),
            start_date="2026-01-22",
            end_date="2026-01-30",
        )
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["data"]["first_replay_bar"], "2026-01-22")
        self.assertEqual(result["data"]["last_replay_bar"], "2026-01-30")
        self.assertFalse(result["safety"]["rules_generated_or_optimized"])
        self.assertFalse(result["safety"]["sealed_holdout_used"])
        self.assertEqual([x["cost_multiplier"] for x in result["cost_sensitivity"]], [1, 2, 3])

    def test_rejects_replay_on_or_before_selection_cutoff(self):
        dataset = {
            "generated_at_utc": "2026-11-21T00:00:00+00:00",
            "holdout_start": "2026-11-20",
            "universe_size": 2,
            "symbols": {"AAA": make_rows(), "BBB": make_rows()},
        }
        with self.assertRaises(ValueError):
            replay_frozen_candidate(
                dataset, make_candidate(),
                start_date="2026-01-21",
                end_date="2026-01-30",
            )

    def test_rejects_window_that_touches_sealed_holdout(self):
        dataset = {
            "generated_at_utc": "2026-11-21T00:00:00+00:00",
            "holdout_start": "2026-11-20",
            "universe_size": 2,
            "symbols": {"AAA": make_rows(), "BBB": make_rows()},
        }
        with self.assertRaises(ValueError):
            replay_frozen_candidate(
                dataset, make_candidate(),
                start_date="2026-01-22",
                end_date="2026-11-20",
            )


if __name__ == "__main__":
    unittest.main()
