import unittest

from research_agent.options_probe import decimal_value, quote_quality, strike_distance


class OptionsProbeTests(unittest.TestCase):
    def test_decimal_value_accepts_finam_decimal_object(self):
        self.assertEqual(decimal_value({"value": "12.5"}), 12.5)

    def test_decimal_value_handles_missing(self):
        self.assertIsNone(decimal_value(None))

    def test_quote_quality_rejects_crossed_market(self):
        result = quote_quality({"bid": {"value": "11"}, "ask": {"value": "10"}})
        self.assertFalse(result["quote_valid"])
        self.assertIsNone(result["spread_pct_of_mid"])

    def test_quote_quality_calculates_spread(self):
        result = quote_quality({
            "bid": {"value": "9"},
            "ask": {"value": "11"},
            "bid_size": {"value": "2"},
            "ask_size": {"value": "3"},
            "timestamp": "2026-11-26T10:00:00Z",
        })
        self.assertTrue(result["quote_valid"])
        self.assertEqual(result["spread_pct_of_mid"], 20.0)

    def test_quote_quality_marks_stale_quote(self):
        from datetime import datetime, timezone

        result = quote_quality({
            "bid": "9",
            "ask": "11",
            "timestamp": "2026-11-26T10:00:00Z",
        }, now=datetime(2026, 11, 26, 10, 31, tzinfo=timezone.utc))
        self.assertEqual(result["quote_age_seconds"], 1860)
        self.assertFalse(result["quote_fresh_5m"])
        self.assertTrue(result["quote_stale_30m"])

    def test_strike_distance_uses_underlying_price(self):
        self.assertEqual(strike_distance({"strike": {"value": "100"}}, 104), 4)


if __name__ == "__main__":
    unittest.main()
