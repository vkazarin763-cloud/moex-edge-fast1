import unittest
from datetime import datetime, timezone

from research_agent.core import Candle
from research_agent.finam_market_data import FinamBar
from research_agent.finam_timeframe_crosscheck import _completed_h1


class FinamTimeframeRunnerTests(unittest.TestCase):
    def test_completed_h1_filter_uses_moscow_local_hour_for_moex(self):
        now = datetime(2026, 11, 20, 5, 30, tzinfo=timezone.utc)  # 08:30 Moscow
        rows = [
            Candle(datetime(2026, 11, 20, 6), 1, 1, 1, 1, 10),
            Candle(datetime(2026, 11, 20, 7), 1, 1, 1, 1, 10),
            Candle(datetime(2026, 11, 20, 8), 1, 1, 1, 1, 10),
        ]
        completed = _completed_h1(rows, now=now, finam=False)
        self.assertEqual([row.timestamp.hour for row in completed], [6, 7])

    def test_completed_h1_filter_aligns_utc_finam_timestamps(self):
        now = datetime(2026, 11, 20, 5, 30, tzinfo=timezone.utc)
        rows = [
            FinamBar(datetime(2026, 11, 20, 3, tzinfo=timezone.utc),
                     1, 1, 1, 1, 10, False),
            FinamBar(datetime(2026, 11, 20, 4, tzinfo=timezone.utc),
                     1, 1, 1, 1, 10, False),
            FinamBar(datetime(2026, 11, 20, 5, tzinfo=timezone.utc),
                     1, 1, 1, 1, 10, False),
        ]
        completed = _completed_h1(rows, now=now, finam=True)
        self.assertEqual(
            [row.timestamp.hour for row in completed], [3, 4]
        )

    def test_completed_h1_filter_keeps_exactly_elapsed_hour(self):
        now = datetime(2026, 11, 20, 5, 0, tzinfo=timezone.utc)
        row = FinamBar(datetime(2026, 11, 20, 4, tzinfo=timezone.utc),
                       1, 1, 1, 1, 10, None)
        self.assertEqual(len(_completed_h1([row], now=now, finam=True)), 1)

    def test_completed_h1_filter_excludes_an_hour_that_has_not_elapsed(self):
        now = datetime(2026, 11, 20, 5, 30, tzinfo=timezone.utc)
        row = FinamBar(datetime(2026, 11, 20, 5, tzinfo=timezone.utc),
                       1, 1, 1, 1, 10, False)
        self.assertEqual(_completed_h1([row], now=now, finam=True), [])


if __name__ == "__main__":
    unittest.main()
