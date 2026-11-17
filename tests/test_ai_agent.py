import unittest

import ai_agent


class KellySizingTests(unittest.TestCase):
    def test_default_fraction_with_fewer_than_ten_closed_trades(self):
        self.assertEqual(ai_agent.get_kelly_pct({"closed_trades": []}, "Keltner"), 0.10)

    def test_uses_only_trades_from_selected_strategy(self):
        portfolio = {
            "closed_trades": [
                {"strategy": "Keltner", "pnl": 100},
                {"strategy": "Keltner", "pnl": 100},
                {"strategy": "Other", "pnl": -500},
            ]
        }
        self.assertEqual(ai_agent.get_kelly_pct(portfolio, "Keltner"), 0.10)

    def test_kelly_is_bounded(self):
        portfolio = {
            "closed_trades": [
                {"strategy": "Keltner", "pnl": 100}
                for _ in range(10)
            ]
        }
        self.assertEqual(ai_agent.get_kelly_pct(portfolio, "Keltner"), 0.20)


if __name__ == "__main__":
    unittest.main()
