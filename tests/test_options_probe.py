import unittest

from research_agent.options_probe import summarize_historical_bars


class HistoricalOptionBarsTests(unittest.TestCase):
    def test_summarizes_ohlc_without_claiming_bid_ask(self):
        payload = {
            "bars": [
                {
                    "timestamp": "2026-11-25T10:00:00Z",
                    "open": {"value": "27.1"},
                    "high": {"value": "27.8"},
                    "low": {"value": "26.9"},
                    "close": {"value": "27.5"},
                    "volume": {"value": "120"},
                },
                {
                    "timestamp": "2026-11-25T10:05:00Z",
                    "open": {"value": "27.5"},
                    "high": {"value": "27.9"},
                    "low": {"value": "27.2"},
                    "close": {"value": "27.7"},
                    "volume": {"value": "80"},
                },
            ]
        }
        result = summarize_historical_bars(payload)
        self.assertEqual(result["bar_count"], 2)
        self.assertEqual(result["first_bar"]["close"], 27.5)
        self.assertEqual(result["last_bar"]["close"], 27.7)
        self.assertFalse(result["contains_historical_bid_ask"])

    def test_empty_bars_are_reported_as_empty(self):
        result = summarize_historical_bars({"bars": []})
        self.assertEqual(result["bar_count"], 0)
        self.assertIsNone(result["first_bar"])
        self.assertIsNone(result["last_bar"])


if __name__ == "__main__":
    unittest.main()
