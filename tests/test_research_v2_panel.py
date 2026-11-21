import unittest
from datetime import date, timedelta

from research_agent.v2.panel import (
    cross_sectional_momentum_12_1,
    relative_strength_vs_imoex,
)


def make_bars(count=253, slope=1.0):
    first_day = date(2025, 1, 1)
    bars = []
    for i in range(count):
        close = 100.0 + slope * i
        bars.append({
            "timestamp": (first_day + timedelta(days=i)).isoformat(),
            "close": close,
            "high": close + 1.0,
        })
    return bars


class V2PanelResearchTests(unittest.TestCase):
    def test_cross_sectional_rank_uses_point_in_time_universe(self):
        panel = {
            f"T{i:02d}": make_bars(slope=float(i + 1))
            for i in range(10)
        }
        result = cross_sectional_momentum_12_1(
            panel,
            as_of=panel["T00"][-1]["timestamp"],
            price_basis_status="verified_same_share",
        )
        self.assertEqual(result["status"], "READY_FOR_RESEARCH")
        self.assertEqual(result["universe_size"], 10)
        self.assertEqual(result["ranked"][0]["ticker"], "T09")
        self.assertEqual(result["ranked"][0]["cohort"], "LONG_CANDIDATE")
        self.assertEqual(result["ranked"][-1]["ticker"], "T00")
        self.assertEqual(result["ranked"][-1]["cohort"], "SHORT_CANDIDATE")

    def test_cross_sectional_fails_closed_without_price_basis(self):
        panel = {f"T{i:02d}": make_bars() for i in range(10)}
        result = cross_sectional_momentum_12_1(
            panel, as_of=panel["T00"][-1]["timestamp"]
        )
        self.assertEqual(result["status"], "DATA_NOT_READY")
        self.assertFalse(result["eligible_for_performance_test"])

    def test_cross_sectional_rejects_small_universe(self):
        panel = {f"T{i:02d}": make_bars() for i in range(4)}
        result = cross_sectional_momentum_12_1(
            panel,
            as_of=panel["T00"][-1]["timestamp"],
            price_basis_status="verified_same_share",
        )
        self.assertEqual(result["status"], "INSUFFICIENT_UNIVERSE")

    def test_cross_sectional_excludes_missing_as_of_bar(self):
        panel = {f"T{i:02d}": make_bars() for i in range(10)}
        panel["T09"] = panel["T09"][:-1]
        result = cross_sectional_momentum_12_1(
            panel,
            as_of=panel["T00"][-1]["timestamp"],
            price_basis_status="verified_same_share",
        )
        self.assertEqual(result["status"], "INSUFFICIENT_UNIVERSE")
        self.assertEqual(result["excluded"]["T09"], "NO_EXACT_AS_OF_BAR")

    def test_relative_strength_requires_synchronized_anchors(self):
        security = make_bars(127, slope=1.5)
        imoex = make_bars(127, slope=1.0)
        result = relative_strength_vs_imoex(
            security,
            imoex,
            as_of=security[-1]["timestamp"],
            price_basis_status="verified_adjusted",
        )
        self.assertEqual(result["status"], "READY_FOR_RESEARCH")
        self.assertGreater(result["excess_return"], 0)
        self.assertIsNone(result.get("signal"))

    def test_relative_strength_rejects_different_anchor_sessions(self):
        security = make_bars(127, slope=1.5)
        imoex = make_bars(127, slope=1.0)
        imoex.pop(10)
        result = relative_strength_vs_imoex(
            security,
            imoex,
            as_of=security[-1]["timestamp"],
            price_basis_status="verified_same_share",
        )
        self.assertEqual(result["status"], "UNSYNCHRONIZED_DATA")

    def test_relative_strength_fails_closed_without_price_basis(self):
        security = make_bars(127)
        imoex = make_bars(127)
        result = relative_strength_vs_imoex(
            security, imoex, as_of=security[-1]["timestamp"]
        )
        self.assertEqual(result["status"], "DATA_NOT_READY")

    def test_relative_strength_requires_full_history(self):
        security = make_bars(126)
        imoex = make_bars(126)
        result = relative_strength_vs_imoex(
            security,
            imoex,
            as_of=security[-1]["timestamp"],
            price_basis_status="verified_same_share",
        )
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")


if __name__ == "__main__":
    unittest.main()
