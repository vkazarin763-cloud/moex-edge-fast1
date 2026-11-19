import unittest
from datetime import datetime, timedelta

from research_agent.core import Candle, Trade
from research_agent.regime import market_breadth_regime_report


def series(count=205, rising=True):
    start = datetime(2025, 1, 1)
    rows = []
    for i in range(count):
        close = 100.0 + i if rising else 500.0 - i
        rows.append(Candle(
            start + timedelta(days=i),
            close, close + 1.0, close - 1.0, close, 1000.0,
        ))
    return rows


def trade(signal_time, strategy="Donchian20", net_return=0.05):
    return Trade(
        strategy=strategy, direction=1,
        signal_time=signal_time,
        entry_time=signal_time + timedelta(days=1),
        exit_time=signal_time + timedelta(days=2),
        entry_price=100.0, exit_price=105.0,
        net_return=net_return, status="CLOSED", exit_reason="TEST",
    )


class MarketBreadthRegimeTests(unittest.TestCase):
    def test_bullish_breadth_and_trade_assignment(self):
        data = {f"UP{i:02d}": series(rising=True) for i in range(20)}
        signal_time = data["UP00"][-1].timestamp
        report = market_breadth_regime_report(
            data, [("UP00", trade(signal_time))], min_tickers=20,
        )
        self.assertEqual(report["by_regime"]["BULLISH"]["closed_trades"], 1)
        self.assertEqual(report["by_regime"]["BEARISH"]["closed_trades"], 0)
        self.assertEqual(report["by_strategy"]["Donchian20"]["BULLISH"]["closed_trades"], 1)

    def test_bearish_and_neutral_breadth_are_distinguished(self):
        bearish = {f"DN{i:02d}": series(rising=False) for i in range(20)}
        when = bearish["DN00"][-1].timestamp
        report = market_breadth_regime_report(
            bearish, [("DN00", trade(when))], min_tickers=20,
        )
        self.assertEqual(report["by_regime"]["BEARISH"]["closed_trades"], 1)

        mixed = {f"UP{i:02d}": series(rising=True) for i in range(10)}
        mixed.update({f"DN{i:02d}": series(rising=False) for i in range(10)})
        when = mixed["UP00"][-1].timestamp
        report = market_breadth_regime_report(
            mixed, [("UP00", trade(when))], min_tickers=20,
        )
        self.assertEqual(report["by_regime"]["NEUTRAL"]["closed_trades"], 1)

    def test_insufficient_breadth_and_stale_regime_are_unknown(self):
        data = {f"UP{i:02d}": series(rising=True) for i in range(20)}
        last = data["UP00"][-1].timestamp
        too_few = market_breadth_regime_report(
            data, [("UP00", trade(last))], min_tickers=21,
        )
        self.assertEqual(too_few["by_regime"]["UNKNOWN"]["closed_trades"], 1)

        stale_time = last + timedelta(days=4)
        stale = market_breadth_regime_report(
            data, [("UP00", trade(stale_time))], min_tickers=20,
            max_staleness_days=3,
        )
        self.assertEqual(stale["by_regime"]["UNKNOWN"]["closed_trades"], 1)

    def test_invalid_thresholds_are_rejected(self):
        data = {"UP": series()}
        for kwargs in (
            {"bullish_threshold": 0.4, "bearish_threshold": 0.4},
            {"bullish_threshold": 1.1, "bearish_threshold": 0.4},
            {"min_tickers": 0},
            {"max_staleness_days": -1},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    market_breadth_regime_report(data, [], **kwargs)


if __name__ == "__main__":
    unittest.main()
