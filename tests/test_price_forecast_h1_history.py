import unittest

from research_agent.price_forecast_24h.collector import merge_cumulative_h1


def candle(timestamp, close):
    return {
        "timestamp": timestamp,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1,
    }


class CumulativeH1HistoryTests(unittest.TestCase):
    def test_appends_new_bars_and_deduplicates_timestamps(self):
        history = {
            "schema_version": 1,
            "source": "Finam H1",
            "symbols": {
                "SBER": {"candles": [candle("2026-11-24T10:00:00+00:00", 100)]}
            },
        }
        delta = {
            "generated_at_utc": "2026-11-25T20:00:00+00:00",
            "symbols": {
                "SBER": {
                    "H1": [
                        candle("2026-11-24T10:00:00+00:00", 999),
                        candle("2026-11-25T10:00:00+00:00", 101),
                    ]
                },
                "GAZP": {
                    "H1": [candle("2026-11-25T10:00:00+00:00", 200)]
                },
            },
        }
        result = merge_cumulative_h1(delta, history)
        sber = result["symbols"]["SBER"]["candles"]
        self.assertEqual(len(sber), 2)
        self.assertEqual(sber[0]["close"], 100)  # existing canonical row is retained
        self.assertEqual(sber[1]["close"], 101)
        self.assertEqual(len(result["symbols"]["GAZP"]["candles"]), 1)
        self.assertEqual(result["symbols"]["SBER"]["first_timestamp"], sber[0]["timestamp"])
        self.assertEqual(result["symbols"]["SBER"]["last_timestamp"], sber[-1]["timestamp"])
        self.assertEqual(result["updated_at_utc"], delta["generated_at_utc"])


if __name__ == "__main__":
    unittest.main()
