import unittest
from datetime import datetime, timedelta

from research_agent.core import Candle, Trade
from research_agent.portfolio import PortfolioTrade, simulate_portfolio
from research_agent.mark_to_market import simulate_mark_to_market


def make_trade(ticker, entry, exit, net_return=0.10, direction=1, strategy="S"):
    return PortfolioTrade(ticker, Trade(
        strategy=strategy,
        direction=direction,
        signal_time=entry - timedelta(days=1),
        entry_time=entry,
        exit_time=exit,
        entry_price=100.0,
        exit_price=100.0 * (1.0 + direction * net_return),
        net_return=net_return,
        status="CLOSED",
        exit_reason="TEST",
    ))


def candle(day, close, ticker_open=None):
    ts = datetime.fromisoformat(day)
    op = close if ticker_open is None else ticker_open
    return Candle(ts, op, max(op, close) * 1.01, min(op, close) * 0.99, close, 1000.0)


class MarkToMarketPortfolioTests(unittest.TestCase):
    def test_intratrade_drawdown_is_visible_even_when_trade_closes_profitably(self):
        entry = datetime(2026, 1, 1, 10)
        exit_time = datetime(2026, 1, 4)
        candidates = [make_trade("AAA", entry, exit_time, net_return=0.10)]
        marks = {"AAA": [
            candle("2026-01-01", 100.0),  # Entry-date daily bar is not usable.
            candle("2026-01-02", 90.0),
            candle("2026-01-03", 95.0),
        ]}
        report = simulate_mark_to_market(candidates, marks, max_positions=1)
        self.assertAlmostEqual(report["final_realized_equity_normalized"], 1.10)
        self.assertLess(report["max_mark_to_market_drawdown"], -0.08)
        self.assertAlmostEqual(report["max_realized_drawdown"], 0.0)
        jan2 = next(row for row in report["equity_curve"] if row["timestamp"] == "2026-01-02T00:00:00")
        self.assertIsNotNone(jan2["mark_to_market_equity"])

    def test_future_candle_is_never_used_for_asof_mark(self):
        entry = datetime(2026, 1, 1, 10)
        middle = datetime(2026, 1, 2, 10)
        exit_time = datetime(2026, 1, 4)
        candidates = [
            make_trade("AAA", entry, exit_time),
            make_trade("BBB", middle, middle, net_return=0.0),
        ]
        marks = {"AAA": [candle("2026-01-03", 50.0)]}
        report = simulate_mark_to_market(candidates, marks, max_positions=2)
        middle_row = next(row for row in report["equity_curve"] if row["timestamp"] == middle.isoformat())
        self.assertIsNone(middle_row["mark_to_market_equity"])
        self.assertEqual(middle_row["unmarked_positions"][0]["reason"], "NO_CANDLE_AT_OR_BEFORE_AS_OF_TIME")

    def test_stale_mark_makes_mtm_equity_unavailable(self):
        entry = datetime(2026, 1, 1, 10)
        stale_check = datetime(2026, 1, 10)
        exit_time = datetime(2026, 1, 12)
        candidates = [
            make_trade("AAA", entry, exit_time),
            make_trade("BBB", stale_check, stale_check, net_return=0.0),
        ]
        marks = {"AAA": [candle("2026-01-02", 101.0)]}
        report = simulate_mark_to_market(
            candidates, marks, max_positions=2, max_mark_staleness_days=3
        )
        row = next(item for item in report["equity_curve"] if item["timestamp"] == stale_check.isoformat())
        self.assertIsNone(row["mark_to_market_equity"])
        self.assertEqual(row["unmarked_positions"][0]["reason"], "STALE_MARK")

    def test_missing_ticker_candles_do_not_create_a_fabricated_mark(self):
        entry = datetime(2026, 1, 1, 10)
        checkpoint = datetime(2026, 1, 2, 10)
        exit_time = datetime(2026, 1, 4)
        candidates = [
            make_trade("AAA", entry, exit_time),
            make_trade("BBB", checkpoint, checkpoint, net_return=0.0),
        ]
        report = simulate_mark_to_market(candidates, {}, max_positions=2)
        row = next(item for item in report["equity_curve"] if item["timestamp"] == checkpoint.isoformat())
        self.assertIsNone(row["mark_to_market_equity"])
        self.assertEqual(row["unmarked_positions"][0]["reason"], "NO_CANDLE_AT_OR_BEFORE_AS_OF_TIME")

    def test_entry_date_candle_is_not_used_as_close_mark(self):
        entry = datetime(2026, 1, 1, 10)
        checkpoint = datetime(2026, 1, 2, 10)
        exit_time = datetime(2026, 1, 4)
        candidates = [
            make_trade("AAA", entry, exit_time),
            make_trade("BBB", checkpoint, checkpoint, net_return=0.0),
        ]
        marks = {"AAA": [candle("2026-01-01", 150.0)]}
        report = simulate_mark_to_market(candidates, marks, max_positions=2)
        row = next(item for item in report["equity_curve"] if item["timestamp"] == checkpoint.isoformat())
        self.assertIsNone(row["mark_to_market_equity"])
        self.assertEqual(row["unmarked_positions"][0]["reason"], "NO_POST_ENTRY_CANDLE")


    def test_zero_duration_exit_order_matches_portfolio_replay(self):
        when = datetime(2026, 1, 1, 10)
        end = datetime(2026, 1, 3)
        candidates = [
            make_trade("AAA", when, when, net_return=0.10),
            make_trade("BBB", when, end, net_return=0.10),
        ]
        marks = {
            "AAA": [candle("2026-01-01", 100.0)],
            "BBB": [
                candle("2026-01-01", 100.0),
                candle("2026-01-02", 101.0),
            ],
        }

        portfolio = simulate_portfolio(candidates, max_positions=1)
        marked = simulate_mark_to_market(candidates, marks, max_positions=1)

        self.assertEqual(marked["closed_trades_accepted"], portfolio["closed_trades_accepted"])
        self.assertEqual(marked["skipped_position_limit"], portfolio["skipped_position_limit"])
        self.assertEqual(marked["skipped_ticker_overlap"], portfolio["skipped_ticker_overlap"])
        self.assertAlmostEqual(
            marked["final_realized_equity_normalized"],
            portfolio["final_equity_normalized"],
        )

if __name__ == "__main__":
    unittest.main()
