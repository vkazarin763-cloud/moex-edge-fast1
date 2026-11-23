import unittest
from datetime import datetime

from research_agent.core import Candle
from research_agent.moex_five_timeframe_audit import aggregate_h4, aggregate_m15, resolve_native_frames


class FiveTimeframeAggregationTests(unittest.TestCase):
    def test_stage_one_configs_do_not_request_m1(self):
        self.assertEqual(resolve_native_frames(["A", "B", "C", "D"]), {"W1", "D1", "H1"})

    def test_config_e_adds_m1_only_for_m15(self):
        self.assertEqual(resolve_native_frames(["E"]), {"W1", "D1", "H1", "M1"})

    def test_unknown_config_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_native_frames(["Z"])

    def test_m15_only_emits_complete_session_local_groups(self):
        rows = [
            Candle(datetime(2026, 1, 5, 10, m), 100, 102, 99, 101, 10)
            for m in range(15)
        ]
        result = aggregate_m15(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].timestamp, datetime(2026, 1, 5, 10, 0))
        self.assertEqual(result[0].volume, 150)

    def test_m15_does_not_bridge_session_break_or_emit_partial(self):
        rows = [
            Candle(datetime(2026, 1, 5, 18, m), 100, 102, 99, 101, 10)
            for m in range(45, 60)
        ]
        self.assertEqual(aggregate_m15(rows), [])

    def test_h4_requires_four_consecutive_hours_in_same_session(self):
        rows = [
            Candle(datetime(2026, 1, 5, h), 100, 102, 99, 101, 10)
            for h in range(10, 14)
        ]
        result = aggregate_h4(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].timestamp, datetime(2026, 1, 5, 10))
        self.assertEqual(result[0].volume, 40)

    def test_h4_does_not_bridge_sessions_or_emit_partial(self):
        rows = [
            Candle(datetime(2026, 1, 5, h), 100, 102, 99, 101, 10)
            for h in (17, 19, 20, 21)
        ]
        self.assertEqual(aggregate_h4(rows), [])


if __name__ == "__main__":
    unittest.main()
