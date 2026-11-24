"""Offline tests for the isolated Finam two-strategy D1 research runner."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from research_agent import finam_strategy_backtest as research
from research_agent.finam_market_data import FinamBar
from research_agent.core import Candle, Signal


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
        for index in range(250):
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
            research, "RefreshingFinamClient", return_value=self.client
        ):
            report = research.run("test-token")
        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(report["strategies"], ["Donchian20","EMA20x50","RSI14Trend50","MACD12x26","ADX14Trend","Keltner20x2ATR","Bollinger20x2","VolumeBreakout","BreakoutRetest","EngulfingTrend","PinBarTrend","SqueezeBreakout","TrendMomentumConfirm","TrendVolumeBreakout","ADXDonchian","CandleVolumeConfirm"])
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

    def test_direction_forecast_reuses_finam_d1_data_and_never_calls_moex_iss(self):
        with patch.object(research, "TICKERS", ("SBER",)), patch.object(
            research, "RefreshingFinamClient", return_value=self.client
        ), patch("research_agent.direction_forecast.TICKERS", ("SBER",)), patch(
            "research_agent.direction_forecast._fetch_d1_model_rows",
            side_effect=AssertionError("Finam D1 candles must be reused; no MOEX ISS request"),
        ):
            report = research.run("test-token")
        forecast = report["direction_forecast_research"]
        self.assertEqual(forecast["source"], "Finam Trade API native D1 candles supplied by the caller")
        self.assertEqual(forecast["holdout_bars_used"], 0)
        self.assertEqual(forecast["symbols_with_eligible_history"], 1)
        self.assertEqual(len(self.client.calls), 1)
        forecasts = forecast["historical_latest_forecasts"]["forecasts"]
        by_horizon = {item["horizon_sessions"]: item for item in forecasts if item.get("ticker") == "SBER"}
        self.assertEqual(set(by_horizon), {1, 5, 20})
        for item in by_horizon.values():
            self.assertEqual(item["status"], "HISTORICAL_FORECAST_ONLY")
            self.assertAlmostEqual(
                item["probability_down"] + item["probability_sideways"] + item["probability_up"],
                1.0, places=10,
            )
            self.assertFalse(item["probabilities_are_calibrated"])

    def test_snapshot_bars_are_excluded(self):
        snapshot = self.bars[-1]
        self.bars[-1] = FinamBar(
            timestamp=snapshot.timestamp, open=snapshot.open, high=snapshot.high,
            low=snapshot.low, close=snapshot.close, volume=snapshot.volume,
            is_data_snapshot=True,
        )
        with patch.object(research, "TICKERS", ("SBER",)), patch.object(
            research, "RefreshingFinamClient", return_value=self.client
        ):
            report = research.run("test-token")
        self.assertEqual(report["data_audit"]["SBER"]["snapshot_true_excluded"], 1)
        self.assertEqual(report["data_audit"]["SBER"]["retained_completed_bars"], 89)

    def test_chandelier_exit_has_no_fixed_stop_target_or_time_limit(self):
        self.assertIsNone(research.BASE_CONFIG.stop_pct)
        self.assertIsNone(research.BASE_CONFIG.target_pct)
        self.assertIsNone(research.BASE_CONFIG.max_bars)
        rows = []
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for index in range(32):
            price = 100 + index if index <= 22 else 122 - (index - 22) * 3
            rows.append(Candle(
                timestamp=start + timedelta(days=index),
                open=float(price), high=float(price + 1),
                low=float(price - 1), close=float(price), volume=1000.0,
            ))
        trades = research._chandelier_backtest(
            rows, [Signal(20, 1, "RSI14Trend50")], research.BASE_CONFIG
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].status, "CLOSED")
        self.assertEqual(trades[0].exit_reason, "CHANDELIER_EXIT")
        self.assertEqual(trades[0].exit_time, rows[25].timestamp)


if __name__ == "__main__":
    unittest.main()
