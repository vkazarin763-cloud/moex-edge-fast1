import unittest
from datetime import datetime, timezone

from research_agent.finam_market_data import FinamBar
from research_agent.multi_timeframe import collect_multi_timeframe


class FakeFinamClient:
    def __init__(self):
        self.calls = []

    def fetch_bars(self, symbol, timeframe, start, end):
        self.calls.append((symbol, timeframe, start, end))
        if timeframe != "TIME_FRAME_D":
            return []
        return [
            FinamBar(
                datetime(2025, 11, 25, 5, 0, tzinfo=timezone.utc),
                100.0, 103.0, 99.0, 102.0, 1000.0, False,
            ),
            FinamBar(
                datetime(2026, 11, 20, 5, 0, tzinfo=timezone.utc),
                102.0, 104.0, 101.0, 103.0, 1200.0, False,
            ),
            # Current Moscow trading date: request must accept this timestamp,
            # but collection must exclude it until the Moscow date is over.
            FinamBar(
                datetime(2026, 11, 24, 5, 0, tzinfo=timezone.utc),
                103.0, 105.0, 102.0, 104.0, 1300.0, False,
            ),
        ]


class MultiTimeframeFinamD1Tests(unittest.TestCase):
    def test_d1_accepts_current_session_timestamp_but_excludes_unclosed_moscow_date(self):
        client = FakeFinamClient()
        report = collect_multi_timeframe(
            ["SBER"],
            api_token="test-token",
            now=datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc),
            frames=["D1"],
            finam_client=client,
        )

        daily = report["results"]["SBER"]["D1"]
        self.assertEqual(daily["status"], "OK")
        self.assertEqual(daily["source"], "Finam")
        self.assertEqual(daily["completed_bars"], 2)
        self.assertEqual(daily["raw_bars"], 3)
        self.assertEqual(daily["incomplete_bars_excluded"], 1)
        self.assertEqual(
            client.calls,
            [(
                "SBER@MISX",
                "TIME_FRAME_D",
                datetime(2025, 11, 24, 12, 0, tzinfo=timezone.utc),
                datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc),
            )],
        )

    def test_d1_does_not_call_moex_even_when_moex_fetcher_is_supplied(self):
        client = FakeFinamClient()
        def forbidden_moex(*args, **kwargs):
            raise AssertionError("MOEX ISS must not be called for D1 signal candles")

        report = collect_multi_timeframe(
            ["SBER"],
            api_token="test-token",
            now=datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc),
            frames=["D1"],
            finam_client=client,
            moex_history_fetcher=forbidden_moex,
        )
        self.assertEqual(report["timeframes"]["D1"]["source"], "Finam")
        self.assertEqual(report["timeframes"]["D1"]["ok"], 1)


if __name__ == "__main__":
    unittest.main()
