import unittest
from datetime import datetime, timezone

from research_agent.finam_market_data import FinamBar
from research_agent.multi_timeframe import collect_multi_timeframe


class FakeFinamClient:
    def fetch_bars(self, symbol, timeframe, start, end):
        self.calls = getattr(self, "calls", [])
        self.calls.append((symbol, timeframe))
        if timeframe != "TIME_FRAME_D":
            return []
        return [FinamBar(
            datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc),
            100.0, 103.0, 99.0, 102.0, 1000.0, False,
        )]


class MultiTimeframeD1FallbackTests(unittest.TestCase):
    def test_falls_back_to_finam_daily_and_keeps_moex_error(self):
        client = FakeFinamClient()

        def moex_history_failure(*args, **kwargs):
            raise RuntimeError("MOEX ISS HTTP 503")

        report = collect_multi_timeframe(
            ["SBER"],
            api_token="test-token",
            now=datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc),
            frames=["D1"],
            finam_client=client,
            moex_history_fetcher=moex_history_failure,
        )

        daily = report["results"]["SBER"]["D1"]
        self.assertEqual(daily["status"], "OK")
        self.assertEqual(daily["source"], "Finam daily fallback (MOEX ISS unavailable)")
        self.assertIn("MOEX ISS HTTP 503", daily["moex_iss_error"])
        self.assertEqual(daily["completed_bars"], 1)
        self.assertEqual(client.calls, [("SBER@MISX", "TIME_FRAME_D")])


if __name__ == "__main__":
    unittest.main()
