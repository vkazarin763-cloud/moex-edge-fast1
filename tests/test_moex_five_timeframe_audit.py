import unittest
from datetime import datetime

from research_agent.core import Candle
from research_agent.moex_five_timeframe_audit import aggregate_h4, aggregate_m15


class FiveTimeframeAggregationTests(unittest.TestCase):
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
            for h in (17, 19, 20, 21, 22)
        ]
        self.assertEqual(aggregate_h4(rows), [])


if __name__ == "__main__":
    unittest.main()
