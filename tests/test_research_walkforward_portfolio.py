import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from research_agent.core import BacktestConfig, Candle, Signal, Trade
from research_agent.portfolio import PortfolioTrade, simulate_portfolio, walk_forward_portfolio_report


def daily_candles(count, start=None):
    start = start or datetime(2026, 1, 1)
    return [
        Candle(
            start + timedelta(days=i),
            100.0 + i,
            101.0 + i,
            99.0 + i,
            100.5 + i,
            1000.0,
        )
        for i in range(count)
    ]


class WalkForwardPortfolioTests(unittest.TestCase):
    def test_each_fold_only_receives_its_own_candles_and_entries(self):
        rows = daily_candles(61)
        generated_history_lengths = []
        backtest_windows = []

        def fake_generate(history):
            generated_history_lengths.append(len(history))
            index = 55 if len(history) == 58 else 58
            return [Signal(index, 1, "Donchian20")]

        def fake_backtest(history, signals, config):
            backtest_windows.append((history[signals[0].index].timestamp, history[-1].timestamp))
            signal = signals[0]
            entry_index = signal.index + 1
            exit_index = signal.index + 2
            return [Trade(
                strategy=signal.strategy,
                direction=signal.direction,
                signal_time=history[signal.index].timestamp,
                entry_time=history[entry_index].timestamp,
                exit_time=history[exit_index].timestamp,
                entry_price=100.0,
                exit_price=110.0,
                net_return=0.10,
                status="CLOSED",
                exit_reason="TEST",
            )]

        with (
            patch("research_agent.portfolio.generate_signals", side_effect=fake_generate),
            patch("research_agent.portfolio.backtest", side_effect=fake_backtest),
        ):
            report = walk_forward_portfolio_report(
                {"AAA": rows}, folds=2, warmup_bars=55,
                config=BacktestConfig(0, 0, None, None, None),
                position_limits=(1,),
            )

        self.assertEqual(generated_history_lengths, [61, 58, 61])
        self.assertEqual(len(report["folds"]), 2)
        self.assertEqual(report["folds"][0]["closed_trades"], 1)
        self.assertEqual(report["folds"][1]["closed_trades"], 1)
        self.assertEqual(report["combined"]["comparisons"]["1"]["closed_trades_accepted"], 2)
        self.assertEqual(report["by_direction"]["LONG"]["candidate_trades"], 2)
        self.assertEqual(report["by_direction"]["SHORT"]["candidate_trades"], 0)
        self.assertEqual(
            report["by_strategy"]["Donchian20"]["by_direction"]["LONG"]["comparisons"]["1"]["closed_trades_accepted"],
            2,
        )
        self.assertEqual(
            report["by_strategy"]["Donchian20"]["by_direction"]["SHORT"]["comparisons"]["1"]["closed_trades_accepted"],
            0,
        )
        self.assertEqual(
            report["continuous_development_replay"]["combined"]["comparisons"]["1"]["closed_trades_accepted"],
            1,
        )
        self.assertLess(backtest_windows[1][1], datetime.fromisoformat(report["folds"][0]["end_exclusive"]))
        self.assertGreaterEqual(backtest_windows[2][0], datetime.fromisoformat(report["folds"][1]["start_inclusive"]))


    def test_real_signal_and_backtest_pipeline_runs_on_synthetic_history(self):
        rows = daily_candles(320)
        report = walk_forward_portfolio_report(
            {"AAA": rows},
            folds=4,
            warmup_bars=200,
            position_limits=(5, 7, 10),
        )
        self.assertEqual(report["status"], "DEVELOPMENT_WALK_FORWARD_PORTFOLIO")
        self.assertEqual(len(report["folds"]), 4)
        self.assertEqual(
            set(report["combined"]["comparisons"]),
            {"5", "7", "10"},
        )
        self.assertIn("v1-frozen-2026-11-19", report["candidate_set_version"])
        self.assertEqual(
            report["continuous_development_replay"]["market_breadth_regime_analysis"]["status"],
            "DESCRIPTIVE_DEVELOPMENT_REGIME_ANALYSIS",
        )
        self.assertEqual(
            set(report["continuous_development_replay"]["mark_to_market_portfolio"]["combined"]),
            {"5", "7", "10"},
        )
        self.assertIn(
            "max_mark_to_market_drawdown",
            report["continuous_development_replay"]["mark_to_market_portfolio"]["combined"]["5"],
        )
        self.assertEqual(set(report["by_strategy"]), {
            "Donchian20", "EMA20x50", "RSI14Trend50",
            "MACD12x26", "Keltner20x2ATR",
        })

    def test_direction_attribution_uses_the_same_shared_position_cap(self):
        entry = datetime(2026, 1, 1)
        exit_time = entry + timedelta(days=1)
        long_trade = Trade(
            strategy="Donchian20", direction=1,
            signal_time=entry - timedelta(days=1),
            entry_time=entry, exit_time=exit_time,
            entry_price=100.0, exit_price=110.0,
            net_return=0.10, status="CLOSED", exit_reason="TEST",
        )
        short_trade = Trade(
            strategy="EMA20x50", direction=-1,
            signal_time=entry - timedelta(days=1),
            entry_time=entry, exit_time=exit_time,
            entry_price=100.0, exit_price=105.0,
            net_return=-0.05, status="CLOSED", exit_reason="TEST",
        )

        result = simulate_portfolio(
            [
                PortfolioTrade("AAA", long_trade),
                PortfolioTrade("BBB", short_trade),
            ],
            max_positions=2,
        )

        attribution = result["accepted_trade_attribution"]
        self.assertEqual(result["closed_trades_accepted"], 2)
        self.assertAlmostEqual(result["total_return"], 0.025)
        self.assertEqual(attribution["by_direction"]["LONG"]["accepted_trades"], 1)
        self.assertEqual(attribution["by_direction"]["SHORT"]["accepted_trades"], 1)
        self.assertAlmostEqual(
            attribution["by_direction"]["LONG"]["realized_pnl_normalized"], 0.05
        )
        self.assertAlmostEqual(
            attribution["by_direction"]["SHORT"]["realized_pnl_normalized"], -0.025
        )
        self.assertAlmostEqual(
            sum(
                row["realized_pnl_normalized"]
                for row in attribution["by_direction"].values()
            ),
            result["total_return"],
        )
        self.assertEqual(
            attribution["by_strategy_direction"]["Donchian20"]["LONG"]["closed_trades"],
            1,
        )
        self.assertEqual(
            attribution["by_strategy_direction"]["EMA20x50"]["SHORT"]["closed_trades"],
            1,
        )

    def test_direction_attribution_respects_shared_cap_rejections(self):
        entry = datetime(2026, 1, 1)
        exit_time = entry + timedelta(days=1)
        candidates = []
        for ticker, direction in (("AAA", 1), ("BBB", -1)):
            trade = Trade(
                strategy="Donchian20", direction=direction,
                signal_time=entry - timedelta(days=1),
                entry_time=entry, exit_time=exit_time,
                entry_price=100.0, exit_price=105.0,
                net_return=0.05, status="CLOSED", exit_reason="TEST",
            )
            candidates.append(PortfolioTrade(ticker, trade))

        result = simulate_portfolio(candidates, max_positions=1)
        attribution = result["accepted_trade_attribution"]["by_direction"]
        self.assertEqual(result["closed_trades_accepted"], 1)
        self.assertEqual(result["skipped_position_limit"], 1)
        self.assertEqual(attribution["LONG"]["accepted_trades"], 1)
        self.assertNotIn("SHORT", attribution)

    def test_ticker_without_required_pre_fold_history_is_skipped(self):
        long_history = daily_candles(61)
        short_history = daily_candles(54, start=datetime(2026, 1, 1, 12))
        with (
            patch("research_agent.portfolio.generate_signals", return_value=[]),
            patch("research_agent.portfolio.backtest", return_value=[]),
        ):
            report = walk_forward_portfolio_report(
                {"AAA": long_history, "SHORT": short_history},
                folds=2, warmup_bars=55, position_limits=(1,),
            )
        self.assertGreater(report["folds"][0]["tickers_skipped_for_short_history"], 0)
        self.assertEqual(report["candidate_trades"], 0)


if __name__ == "__main__":
    unittest.main()
