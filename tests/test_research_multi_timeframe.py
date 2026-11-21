import unittest
from datetime import date, datetime, timezone

from research_agent.multi_timeframe import (
    FINAM_FRAMES, MOEX_FRAMES, RefreshingFinamClient,
    _finam_bar_is_complete, _moex_bar_is_complete, collect_multi_timeframe,
)
from research_agent.finam_market_data import FinamAPIError
from unittest.mock import patch
from research_agent.moex_iss import HistoryRecord
from research_agent.core import Candle
from research_agent.finam_market_data import FinamBar


def fake_history_fetcher(ticker, start, end, *, board):
    return [
        HistoryRecord(date(2026, 7, 1), 10, 100, 102, 99, 101, 500),
        HistoryRecord(date(2026, 7, 2), 0, None, None, None, None, 0),
    ]


class FakeFinam:
    def fetch_bars(self, symbol, timeframe, start, end):
        stamp = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)
        return [
            FinamBar(stamp, 100, 102, 99, 101, 1000, False),
            FinamBar(stamp.replace(hour=11), 101, 103, 100, 102, 1200, True),
            FinamBar(stamp.replace(hour=12), 102, 104, 101, 103, 900, None),
        ]


class MultiTimeframeTests(unittest.TestCase):
    def test_supported_frames_are_explicit_and_disjoint(self):
        self.assertEqual(set(FINAM_FRAMES), {"M1", "M5", "M15", "M30", "H1", "H2", "H4", "H8"})
        self.assertEqual(set(MOEX_FRAMES), {"M10", "W1", "MN", "QR"})
        self.assertFalse(set(FINAM_FRAMES) & set(MOEX_FRAMES))

    def test_collection_keeps_feeds_separate_and_filters_only_true_snapshots(self):
        calls = []

        def moex_fetcher(ticker, start, end, *, interval, board):
            calls.append((ticker, interval, board))
            return [Candle(datetime(2026, 7, 1, 10), 100, 102, 99, 101, 500)]

        result = collect_multi_timeframe(
            ["SBER"], api_token="not-used", now=datetime(2026, 11, 20, 13, tzinfo=timezone.utc),
            moex_fetcher=moex_fetcher, moex_history_fetcher=fake_history_fetcher, finam_client=FakeFinam(),
        )
        sber = result["results"]["SBER"]
        self.assertEqual(sber["M15"]["source"], "Finam")
        self.assertEqual(sber["M15"]["raw_bars"], 3)
        self.assertEqual(sber["M15"]["completed_bars"], 2)
        self.assertEqual(sber["M15"]["snapshot_true_excluded"], 1)
        self.assertEqual(sber["M15"]["snapshot_unknown_retained"], 1)
        self.assertEqual(sber["M10"]["source"], "MOEX ISS")
        self.assertEqual(sber["D1"]["source"], "MOEX ISS TQBR history")
        self.assertEqual(sber["D1"]["completed_bars"], 1)
        self.assertEqual(sber["D1"]["zero_trade_rows_excluded"], 1)
        self.assertEqual(len(sber["W1"]["candles"]), 1)
        self.assertEqual(len(calls), len(MOEX_FRAMES))
        self.assertEqual(result["timeframes"]["M15"]["ok"], 1)
        self.assertIn("does not modify the frozen D1", result["methodology"]["research_isolation"])

    def test_failures_are_isolated_by_symbol_and_timeframe(self):
        class BrokenFinam:
            def fetch_bars(self, *args):
                raise RuntimeError("source unavailable")

        def broken_moex(*args, **kwargs):
            raise RuntimeError("ISS unavailable")

        result = collect_multi_timeframe(
            ["SBER"], api_token="not-used", now=datetime(2026, 11, 20, 13, tzinfo=timezone.utc),
            moex_fetcher=broken_moex, moex_history_fetcher=lambda *a, **k: (_ for _ in ()).throw(RuntimeError('history unavailable')), finam_client=BrokenFinam(),
        )
        self.assertEqual(result["results"]["SBER"]["M1"]["status"], "ERROR")
        self.assertEqual(result["results"]["SBER"]["MN"]["status"], "ERROR")
        self.assertEqual(result["timeframes"]["M1"]["errors"], 1)
        self.assertEqual(result["timeframes"]["QR"]["errors"], 1)


    def test_finam_h1_is_supported_and_unfinished_intervals_are_excluded(self):
        now = datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc)
        self.assertTrue(_finam_bar_is_complete(
            datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc), "H1", now
        ))
        self.assertFalse(_finam_bar_is_complete(
            datetime(2026, 11, 20, 12, 30, tzinfo=timezone.utc), "H1", now
        ))
        self.assertFalse(_finam_bar_is_complete(
            datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc), "M1", now
        ))
        self.assertFalse(_finam_bar_is_complete(
            datetime(2026, 11, 20, 12, 0), "H1", now
        ))

    def test_moex_incomplete_intraday_and_calendar_bars_are_excluded(self):
        now = datetime(2026, 11, 20, 22, 19)
        self.assertTrue(_moex_bar_is_complete(datetime(2026, 11, 20, 22, 0), "M10", now))
        self.assertFalse(_moex_bar_is_complete(datetime(2026, 11, 20, 22, 10), "M10", now))
        self.assertFalse(_moex_bar_is_complete(datetime(2026, 11, 16), "W1", now))
        self.assertTrue(_moex_bar_is_complete(datetime(2026, 11, 9), "W1", now))
        self.assertFalse(_moex_bar_is_complete(datetime(2026, 11, 1), "MN", now))
        self.assertTrue(_moex_bar_is_complete(datetime(2026, 10, 1), "MN", now))
        self.assertFalse(_moex_bar_is_complete(datetime(2026, 10, 1), "QR", now))
        self.assertTrue(_moex_bar_is_complete(datetime(2026, 7, 1), "QR", now))

    def test_finam_client_refreshes_once_after_401(self):
        class FakeClient:
            def __init__(self, should_fail):
                self.should_fail = should_fail

            def fetch_bars(self, *args):
                if self.should_fail:
                    raise FinamAPIError("Finam API returned HTTP 401")
                return ["ok"]

        clients = [FakeClient(True), FakeClient(False)]
        with patch("research_agent.multi_timeframe.FinamMarketDataClient.from_api_token",
                   side_effect=clients) as factory:
            client = RefreshingFinamClient("secret", "app-id")
            self.assertEqual(client.fetch_bars("SBER@MISX", "TIME_FRAME_M1", None, None), ["ok"])
            self.assertEqual(factory.call_count, 2)

    def test_moex_collection_reports_incomplete_bars_excluded(self):
        def moex_fetcher(ticker, start, end, *, interval, board):
            if interval == 10:
                return [
                    Candle(datetime(2026, 11, 20, 22, 0), 100, 102, 99, 101, 500),
                    Candle(datetime(2026, 11, 20, 22, 10), 101, 103, 100, 102, 400),
                ]
            return [
                Candle(datetime(2026, 11, 16), 100, 102, 99, 101, 500),
                Candle(datetime(2026, 11, 9), 101, 103, 100, 102, 400),
            ]
        result = collect_multi_timeframe(
            ["SBER"], api_token="not-used",
            now=datetime(2026, 11, 20, 19, 19, tzinfo=timezone.utc),
            moex_fetcher=moex_fetcher, finam_client=FakeFinam(),
        )
        sber = result["results"]["SBER"]
        self.assertEqual(sber["M10"]["raw_bars"], 2)
        self.assertEqual(sber["M10"]["completed_bars"], 1)
        self.assertEqual(sber["M10"]["incomplete_bars_excluded"], 1)
        self.assertEqual(sber["W1"]["completed_bars"], 1)
        self.assertEqual(sber["W1"]["incomplete_bars_excluded"], 1)


if __name__ == "__main__":
    unittest.main()
