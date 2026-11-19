import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from research_agent.core import BacktestConfig, Candle, Signal, Trade
from research_agent.portfolio import walk_forward_portfolio_report


def candles(count):
    start = datetime(2026, 1, 1)
    return [
        Candle(start + timedelta(days=i), 100+i, 101+i, 99+i, 100.5+i, 1000)
        for i in range(count)
    ]


class ContinuousPortfolioTests(unittest.TestCase):
    def test_continuous_replay_keeps_trade_open_across_fold_boundary(self):
        rows = candles(61)
        boundary = rows[55].timestamp

        def generate(history):
            return [Signal(55, 1, "Donchian20")] if len(history) >= 58 else []

        def simulate(history, signals, config):
            if not signals:
                return []
            if len(history) <= 58:
                return [Trade(
                    strategy="Donchian20", direction=1,
                    signal_time=history[55].timestamp,
                    entry_time=history[56].timestamp,
                    exit_time=None, entry_price=100.0, exit_price=None,
                    net_return=None, status="OPEN", exit_reason="END_OF_FOLD",
                )]
            return [Trade(
                strategy="Donchian20", direction=1,
                signal_time=history[55].timestamp,
                entry_time=history[56].timestamp,
                exit_time=history[59].timestamp,
                entry_price=100.0, exit_price=110.0,
                net_return=0.10, status="CLOSED", exit_reason="TEST_CROSS_FOLD",
            )]

        with (
            patch("research_agent.portfolio.generate_signals", side_effect=generate),
            patch("research_agent.portfolio.backtest", side_effect=simulate),
        ):
            report = walk_forward_portfolio_report(
                {"AAA": rows}, folds=2, warmup_bars=55,
                config=BacktestConfig(0, 0, None, None, None),
                position_limits=(1,),
            )

        continuous = report["continuous_development_replay"]
        self.assertEqual(continuous["candidate_trades"], 1)
        self.assertEqual(
            continuous["combined"]["comparisons"]["1"]["closed_trades_accepted"], 1
        )
        self.assertEqual(report["folds"][0]["open_trades_excluded_at_fold_boundary"], 1)
        self.assertEqual(report["combined"]["comparisons"]["1"]["closed_trades_accepted"], 0)
        self.assertEqual(continuous["development_start_inclusive"], boundary.isoformat())


if __name__ == "__main__":
    unittest.main()
