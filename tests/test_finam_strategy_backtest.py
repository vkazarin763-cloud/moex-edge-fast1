"""Offline tests for the isolated Finam two-strategy D1 research runner."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from research_agent import finam_strategy_backtest as research
from research_agent.finam_market_data import FinamBar


class FakeFinamClient:
    def __init__(self, bars):
        self.bars = bars
        self.calls = []

    def fetch_bars(self, symbol, timeframe, start, end):
        self.calls.append((symbol, timeframe, start, end))
        return self.bars


class FinamStrategyBacktestTests(unittest.TestCase):
    def setUp(self):
        start = datetime(2025, 11, 20, 5, tzinfo=timezone.utc)
        self.bars = []
        previous = 100.0
        for index in range(90):
            close = 100 + index * 0.12 + ((-1) ** (index // 5)) * (index % 5) * 0.8
            open_price = previous
            self.bars.append(FinamBar(
                timestamp=start + timedelta(days=index),
                open=open_price,
                high=max(open_price, close) + 1.0,
                low=min(open_price, close) - 1.0,
                close=close,
                volume=10000.0 + index,
                is_data_snapshot=False,
            ))
            previous = close
        self.client = FakeFinamClient(self.bars)

    def test_requests_exact_365_day_d1_window_and_excludes_holdout(self):
        with patch.object(research, "TICKERS", ("SBER",)), patch.object(
            research.FinamMarketDataClient, "from_api_token", return_value=self.client
        ):
            report = research.run("test-token")
        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(report["strategies"], ["RSI14Trend50", "Keltner20x2ATR"])
        self.assertEqual(len(self.client.calls), 1)
        symbol, timeframe, start, end = self.client.calls[0]
        self.assertEqual((symbol, timeframe), ("SBER@MISX", "TIME_FRAME_D"))
        self.assertEqual(end - start, timedelta(days=365))
        self.assertEqual(report["holdout_start"], "2026-11-20")
        for candles in report["candles"].values():
            self.assertTrue(all(
                datetime.fromisoformat(item["timestamp"]).date().isoformat() < "2026-11-20"
                for item in candles
            ))
        self.assertEqual(report["data_summary"]["symbols_with_usable_history"], 1)

    def test_snapshot_bars_are_excluded(self):
        snapshot = self.bars[-1]
        self.bars[-1] = FinamBar(
            timestamp=snapshot.timestamp, open=snapshot.open, high=snapshot.high,
            low=snapshot.low, close=snapshot.close, volume=snapshot.volume,
            is_data_snapshot=True,
        )
        with patch.object(research, "TICKERS", ("SBER",)), patch.object(
            research.FinamMarketDataClient, "from_api_token", return_value=self.client
        ):
            report = research.run("test-token")
        self.assertEqual(report["data_audit"]["SBER"]["snapshot_true_excluded"], 1)
        self.assertEqual(report["data_audit"]["SBER"]["retained_completed_bars"], 89)


if __name__ == "__main__":
    unittest.main()
