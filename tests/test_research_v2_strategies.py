import unittest
from datetime import date, timedelta

from research_agent.v2.strategies import (
    DataContractError,
    high_52_week_proximity,
    time_series_momentum_12_1,
)


def make_bars(count=253, rising=True):
    bars = []
    first_day = date(2025, 1, 1)
    for i in range(count):
        close = 100.0 + i if rising else 400.0 - i
        bars.append({
            "timestamp": (first_day + timedelta(days=i)).isoformat(),
            "close": close,
            "high": close + 2.0,
        })
    return bars


class V2SingleSecurityStrategyTests(unittest.TestCase):
    def test_unverified_price_basis_fails_closed(self):
        result = time_series_momentum_12_1(make_bars())
        self.assertEqual(result["status"], "DATA_NOT_READY")
        self.assertFalse(result["eligible_for_performance_test"])

    def test_tsm_12_1_positive_return_is_long(self):
        result = time_series_momentum_12_1(
            make_bars(), price_basis_status="verified_same_share"
        )
        self.assertEqual(result["status"], "READY_FOR_RESEARCH")
        self.assertEqual(result["signal"], "LONG")
        self.assertGreater(result["metrics"]["return_12_1"], 0)

    def test_tsm_12_1_negative_return_is_short(self):
        result = time_series_momentum_12_1(
            make_bars(rising=False), price_basis_status="verified_adjusted"
        )
        self.assertEqual(result["signal"], "SHORT")
        self.assertLess(result["metrics"]["return_12_1"], 0)

    def test_tsm_requires_full_lookback(self):
        result = time_series_momentum_12_1(
            make_bars(252), price_basis_status="verified_same_share"
        )
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")

    def test_52_week_high_is_metric_not_directional_signal(self):
        result = high_52_week_proximity(
            make_bars(), price_basis_status="verified_same_share"
        )
        self.assertEqual(result["status"], "READY_FOR_RESEARCH")
        self.assertIsNone(result["signal"])
        self.assertGreater(result["metrics"]["close_to_252_session_high"], 0)

    def test_52_week_high_requires_252_bars(self):
        result = high_52_week_proximity(
            make_bars(251), price_basis_status="verified_same_share"
        )
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")

    def test_fixed_formation_index_ignores_future_bars(self):
        bars = make_bars(260)
        baseline = time_series_momentum_12_1(
            bars, price_basis_status="verified_same_share", formation_index=252
        )
        bars[253]["close"] = 1.0
        bars[253]["high"] = 2.0
        changed_future = time_series_momentum_12_1(
            bars, price_basis_status="verified_same_share", formation_index=252
        )
        self.assertEqual(baseline["signal"], changed_future["signal"])
        self.assertEqual(
            baseline["metrics"]["return_12_1"],
            changed_future["metrics"]["return_12_1"],
        )

    def test_duplicate_or_unsorted_timestamps_are_rejected(self):
        bars = make_bars()
        bars[1]["timestamp"] = bars[0]["timestamp"]
        with self.assertRaises(DataContractError):
            high_52_week_proximity(bars, price_basis_status="verified_same_share")

    def test_invalid_ohlc_is_rejected(self):
        bars = make_bars()
        bars[20]["high"] = bars[20]["close"] - 1
        with self.assertRaises(DataContractError):
            high_52_week_proximity(bars, price_basis_status="verified_same_share")

    def test_invalid_timestamp_is_rejected(self):
        bars = make_bars()
        bars[10]["timestamp"] = "not-a-date"
        with self.assertRaises(DataContractError):
            high_52_week_proximity(bars, price_basis_status="verified_same_share")


if __name__ == "__main__":
    unittest.main()
