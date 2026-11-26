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
                datetime(2025, 11, 23, 5, 0, tzinfo=timezone.utc),
                100.0, 103.0, 99.0, 102.0, 1000.0, False,
            ),
            FinamBar(
                datetime(2026, 11, 20, 5, 0, tzinfo=timezone.utc),
                102.0, 104.0, 101.0, 103.0, 1200.0, False,
            ),
        ]


class MultiTimeframeD1FallbackTests(unittest.TestCase):
    def test_falls_back_to_finam_daily_and_keeps_moex_error(self):
        client = FakeFinamClient()
        now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)

        def moex_history_failure(*args, **kwargs):
            raise RuntimeError("MOEX ISS HTTP 503")

        report = collect_multi_timeframe(
            ["SBER"],
            api_token="test-token",
            now=now,
            frames=["D1"],
            finam_client=client,
            moex_history_fetcher=moex_history_failure,
        )

        daily = report["results"]["SBER"]["D1"]
        self.assertEqual(daily["status"], "OK")
        self.assertEqual(daily["source"], "Finam daily fallback (MOEX ISS unavailable)")
        self.assertIn("MOEX ISS HTTP 503", daily["moex_iss_error"])
        self.assertEqual(daily["completed_bars"], 2)
        self.assertEqual(
            client.calls,
            [(
                "SBER@MISX",
                "TIME_FRAME_D",
                datetime(2025, 11, 23, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc),
            )],
        )


if __name__ == "__main__":
    unittest.main()
