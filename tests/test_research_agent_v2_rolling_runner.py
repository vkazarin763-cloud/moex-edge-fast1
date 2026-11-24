import unittest

from research_agent.v2.rolling_runner import run_rolling_moex_d1_research


def make_rows(n=240):
    rows = []
    for i in range(n):
        p = 100 + i * 0.05 + (i % 5) * 0.1
        rows.append({
            "timestamp": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}T00:00:00",
            "open": p, "high": p + 1, "low": p - 1,
            "close": p + 0.2, "volume": 1000 + i,
        })
    return rows


class RollingRunnerTests(unittest.TestCase):
    def test_runs_sequential_windows_and_keeps_final_holdout_closed(self):
        data = {
            "symbols": {"AAA": make_rows(), "BBB": make_rows()},
            "generated_at_utc": "2026-11-21T00:00:00+00:00",
            "holdout_start": "2026-11-20",
            "universe_size": 2,
            "total_pre_holdout_bars": 480,
            "post_holdout_rows_excluded": 2,
            "validation": {"status": "PASS", "issue_count": 0},
        }
        result = run_rolling_moex_d1_research(
            data, window_starts=(0.25, 0.60), window_width=0.35,
            max_hypotheses_per_symbol=2, resamples=999,
            min_trades_for_inference=20, block_length=5,
        )
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["summary"]["folds_completed"], 2)
        self.assertTrue(result["research_design"]["validation_windows_non_overlapping"])
        self.assertEqual(result["research_design"]["window_width"], 0.35)
        self.assertEqual(result["research_design"]["window_starts"], [0.25, 0.60])
        self.assertTrue(result["research_design"]["this_is_not_an_untouched_final_holdout"])
        self.assertFalse(result["safety"]["final_holdout_used"])
        self.assertEqual(
            result["summary"]["hypotheses"],
            result["global_family"]["family_size"],
        )


if __name__ == "__main__":
    unittest.main()
