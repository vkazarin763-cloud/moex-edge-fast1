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


def verified_basis(panel):
    return {ticker: "verified_same_share" for ticker in panel}


class V2PanelResearchTests(unittest.TestCase):
    def test_cross_sectional_rank_uses_point_in_time_universe(self):
        panel = {f"T{i:02d}": make_bars(slope=float(i + 1)) for i in range(10)}
        result = cross_sectional_momentum_12_1(
            panel,
            as_of=panel["T00"][-1]["timestamp"],
            price_basis_status_by_ticker=verified_basis(panel),
        )
        self.assertEqual(result["status"], "READY_FOR_RESEARCH")
        self.assertEqual(result["universe_size"], 10)
        self.assertEqual(result["ranked"][0]["ticker"], "T09")
        self.assertEqual(result["ranked"][0]["cohort"], "LONG_CANDIDATE")
        self.assertEqual(result["ranked"][-1]["ticker"], "T00")
        self.assertEqual(result["ranked"][-1]["cohort"], "SHORT_CANDIDATE")

    def test_cross_sectional_fails_closed_without_per_ticker_basis(self):
        panel = {f"T{i:02d}": make_bars() for i in range(10)}
        result = cross_sectional_momentum_12_1(
            panel, as_of=panel["T00"][-1]["timestamp"]
        )
        self.assertEqual(result["status"], "DATA_NOT_READY")
        self.assertFalse(result["eligible_for_performance_test"])

    def test_cross_sectional_excludes_unverified_ticker_basis(self):
        panel = {f"T{i:02d}": make_bars() for i in range(10)}
        basis = verified_basis(panel)
        basis["T09"] = "unverified"
        result = cross_sectional_momentum_12_1(
            panel,
            as_of=panel["T00"][-1]["timestamp"],
            price_basis_status_by_ticker=basis,
        )
        self.assertEqual(result["status"], "INSUFFICIENT_VERIFIED_UNIVERSE")
        self.assertEqual(result["excluded"]["T09"], "PRICE_BASIS_NOT_VERIFIED")

    def test_cross_sectional_rejects_small_universe(self):
        panel = {f"T{i:02d}": make_bars() for i in range(4)}
        result = cross_sectional_momentum_12_1(
            panel,
            as_of=panel["T00"][-1]["timestamp"],
            price_basis_status_by_ticker=verified_basis(panel),
        )
        self.assertEqual(result["status"], "INSUFFICIENT_VERIFIED_UNIVERSE")

    def test_cross_sectional_requires_shared_as_of_bar(self):
        panel = {f"T{i:02d}": make_bars() for i in range(10)}
        panel["T09"] = panel["T09"][:-1]
        result = cross_sectional_momentum_12_1(
            panel,
            as_of=panel["T00"][-1]["timestamp"],
            price_basis_status_by_ticker=verified_basis(panel),
        )
        self.assertEqual(result["status"], "UNSYNCHRONIZED_DATA")

    def test_cross_sectional_uses_common_session_anchors(self):
        panel = {f"T{i:02d}": make_bars(slope=float(i + 1)) for i in range(10)}
        panel["T09"] = panel["T09"][:100] + panel["T09"][101:]
        result = cross_sectional_momentum_12_1(
            panel,
            as_of=panel["T00"][-1]["timestamp"],
            price_basis_status_by_ticker=verified_basis(panel),
        )
        self.assertEqual(result["status"], "INSUFFICIENT_COMMON_HISTORY")

    def test_cross_sectional_ignores_future_bars(self):
        panel = {f"T{i:02d}": make_bars() for i in range(10)}
        as_of = panel["T00"][-1]["timestamp"]
        basis = verified_basis(panel)
        baseline = cross_sectional_momentum_12_1(
            panel, as_of=as_of, price_basis_status_by_ticker=basis
        )
        for bars in panel.values():
            bars.append({
                "timestamp": (date.fromisoformat(as_of) + timedelta(days=1)).isoformat(),
                "close": 1.0,
                "high": 2.0,
            })
        changed_future = cross_sectional_momentum_12_1(
            panel, as_of=as_of, price_basis_status_by_ticker=basis
        )
        self.assertEqual(baseline["ranked"], changed_future["ranked"])

    def test_relative_strength_uses_synchronized_anchors(self):
        security = make_bars(127, slope=1.5)
        imoex = make_bars(127, slope=1.0)
        result = relative_strength_vs_imoex(
            security,
            imoex,
            as_of=security[-1]["timestamp"],
            security_price_basis_status="verified_adjusted",
            imoex_price_basis_status="verified_same_share",
        )
        self.assertEqual(result["status"], "READY_FOR_RESEARCH")
        self.assertGreater(result["excess_return"], 0)
        self.assertIsNone(result.get("signal"))

    def test_relative_strength_rejects_different_anchor_sessions(self):
        security = make_bars(127, slope=1.5)
        imoex = make_bars(127, slope=1.0)
        imoex[105]["timestamp"] = (
            date(2025, 1, 1) + timedelta(days=105)
        ).isoformat() + "T12:00:00"
        result = relative_strength_vs_imoex(
            security,
            imoex,
            as_of=security[-1]["timestamp"],
            security_price_basis_status="verified_same_share",
            imoex_price_basis_status="verified_same_share",
        )
        self.assertEqual(result["status"], "UNSYNCHRONIZED_DATA")

    def test_relative_strength_requires_both_price_bases(self):
        security = make_bars(127)
        imoex = make_bars(127)
        result = relative_strength_vs_imoex(
            security,
            imoex,
            as_of=security[-1]["timestamp"],
            security_price_basis_status="verified_same_share",
        )
        self.assertEqual(result["status"], "DATA_NOT_READY")

    def test_relative_strength_requires_full_history(self):
        security = make_bars(126)
        imoex = make_bars(126)
        result = relative_strength_vs_imoex(
            security,
            imoex,
            as_of=security[-1]["timestamp"],
            security_price_basis_status="verified_same_share",
            imoex_price_basis_status="verified_same_share",
        )
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")


if __name__ == "__main__":
    unittest.main()
