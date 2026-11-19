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


if __name__ == "__main__":
    unittest.main()
