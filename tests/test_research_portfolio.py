import unittest
from datetime import datetime, timedelta

from research_agent.core import Trade
from research_agent.portfolio import PortfolioTrade, compare_position_limits, simulate_portfolio


def closed_trade(strategy, entry, exit, net_return):
    return Trade(
        strategy=strategy,
        direction=1,
        signal_time=entry - timedelta(days=1),
        entry_time=entry,
        exit_time=exit,
        entry_price=100.0,
        exit_price=100.0 * (1.0 + net_return),
        net_return=net_return,
        status="CLOSED",
        exit_reason="TEST",
    )


class PortfolioSimulationTests(unittest.TestCase):
    def test_position_cap_cash_only_and_deterministic_entry_order(self):
        start = datetime(2026, 1, 1, 10)
        end = start + timedelta(hours=1)
        candidates = [
            PortfolioTrade("CCC", closed_trade("S", start, end, 0.20)),
            PortfolioTrade("BBB", closed_trade("S", start, end, -0.10)),
            PortfolioTrade("AAA", closed_trade("S", start, end, 0.10)),
        ]
        report = simulate_portfolio(candidates, max_positions=2)
        self.assertEqual(report["closed_trades_accepted"], 2)
        self.assertEqual(report["skipped_position_limit"], 1)
        self.assertEqual(report["max_concurrent_positions"], 2)
        self.assertAlmostEqual(report["final_equity_normalized"], 1.0)
        self.assertEqual(report["win_rate"], 0.5)

    def test_entry_and_exit_on_same_timestamp_are_processed_in_correct_order(self):
        when = datetime(2026, 1, 1, 10)
        report = simulate_portfolio([
            PortfolioTrade("AAA", closed_trade("S", when, when, 0.10))
        ], max_positions=1)
        self.assertEqual(report["closed_trades_accepted"], 1)
        self.assertAlmostEqual(report["final_equity_normalized"], 1.10)
        self.assertIsNone(report["profit_factor"])
        self.assertTrue(report["profit_factor_infinite"])

    def test_only_one_active_position_per_ticker(self):
        start = datetime(2026, 1, 1, 10)
        candidates = [
            PortfolioTrade("AAA", closed_trade("S1", start, start + timedelta(hours=2), 0.10)),
            PortfolioTrade("AAA", closed_trade("S2", start + timedelta(hours=1), start + timedelta(hours=3), 0.20)),
        ]
        report = simulate_portfolio(candidates, max_positions=5)
        self.assertEqual(report["closed_trades_accepted"], 1)
        self.assertEqual(report["skipped_ticker_overlap"], 1)
        self.assertAlmostEqual(report["final_equity_normalized"], 1.02)

    def test_open_trades_are_excluded(self):
        start = datetime(2026, 1, 1, 10)
        open_trade = Trade("S", 1, start, start, None, 100.0, None, None, "OPEN", "END_OF_DATA")
        report = simulate_portfolio([PortfolioTrade("AAA", open_trade)])
        self.assertEqual(report["open_or_incomplete_trades_excluded"], 1)
        self.assertEqual(report["closed_trades_accepted"], 0)
        self.assertEqual(report["final_equity_normalized"], 1.0)

    def test_comparison_replays_same_candidates_for_each_limit(self):
        start = datetime(2026, 1, 1, 10)
        end = start + timedelta(hours=1)
        candidates = [
            PortfolioTrade(ticker, closed_trade("S", start, end, 0.05))
            for ticker in ("AAA", "BBB", "CCC")
        ]
        report = compare_position_limits(candidates, (1, 2, 3))
        self.assertEqual(set(report["comparisons"]), {"1", "2", "3"})
        self.assertEqual(report["comparisons"]["1"]["closed_trades_accepted"], 1)
        self.assertEqual(report["comparisons"]["3"]["closed_trades_accepted"], 3)

    def test_invalid_position_limit_and_return_are_rejected(self):
        with self.assertRaises(ValueError):
            simulate_portfolio([], max_positions=0)
        start = datetime(2026, 1, 1, 10)
        with self.assertRaises(ValueError):
            simulate_portfolio([
                PortfolioTrade("AAA", closed_trade("S", start, start, -1.0))
            ])


    def test_profit_factor_uses_realized_position_pnl(self):
        start = datetime(2026, 1, 1, 10)
        candidates = [
            PortfolioTrade("AAA", closed_trade("S", start, start + timedelta(hours=1), 0.10)),
            PortfolioTrade("BBB", closed_trade("S", start, start + timedelta(hours=1), -0.05)),
        ]
        report = simulate_portfolio(candidates, max_positions=2)
        self.assertAlmostEqual(report["profit_factor"], 2.0)
        self.assertAlmostEqual(report["final_equity_normalized"], 1.025)

    def test_closed_position_is_released_before_new_same_time_entry(self):
        start = datetime(2026, 1, 1, 10)
        middle = start + timedelta(hours=1)
        end = middle + timedelta(hours=1)
        candidates = [
            PortfolioTrade("AAA", closed_trade("S", start, middle, 0.10)),
            PortfolioTrade("BBB", closed_trade("S", middle, end, 0.10)),
        ]
        report = simulate_portfolio(candidates, max_positions=1)
        self.assertEqual(report["closed_trades_accepted"], 2)
        self.assertEqual(report["skipped_position_limit"], 0)
        self.assertAlmostEqual(report["final_equity_normalized"], 1.21)

    def test_invalid_limit_types_are_rejected(self):
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    simulate_portfolio([], max_positions=limit)

    def test_comparison_rejects_invalid_or_duplicate_limits(self):
        start = datetime(2026, 1, 1, 10)
        rows = [PortfolioTrade("AAA", closed_trade("S", start, start, 0.01))]
        for limits in ((), (1, 1), (0, 2), (True, 2)):
            with self.subTest(limits=limits):
                with self.assertRaises(ValueError):
                    compare_position_limits(rows, limits)


    def test_zero_duration_trade_releases_ticker_before_next_same_time_entry(self):
        when = datetime(2026, 1, 1, 10)
        later = when + timedelta(hours=1)
        candidates = [
            PortfolioTrade("AAA", closed_trade("S1", when, when, 0.10)),
            PortfolioTrade("AAA", closed_trade("S2", when, later, 0.10)),
        ]
        report = simulate_portfolio(candidates, max_positions=1)
        self.assertEqual(report["closed_trades_accepted"], 2)
        self.assertEqual(report["skipped_ticker_overlap"], 0)
        self.assertAlmostEqual(report["final_equity_normalized"], 1.21)


if __name__ == "__main__":
    unittest.main()
