import unittest

from research_agent.price_forecast_24h.collector import build_daily_delta


class CollectorDeltaTests(unittest.TestCase):
    def test_first_snapshot_keeps_available_history_and_marks_missing_value(self):
        payload = {
            "generated_at_utc": "2026-11-25T18:00:00+00:00",
            "timezone": "Europe/Moscow",
            "results": {
                "SBER": {
                    "H1": {"source": "Finam", "candles": [
                        {"timestamp": "2026-11-25T10:00:00+00:00"},
                        {"timestamp": "2026-11-25T11:00:00+00:00"},
                    ]},
                    "D1": {"source": "MOEX ISS TQBR history", "candles": [
                        {"timestamp": "2026-11-24T00:00:00", "value": 123456.0},
                        {"timestamp": "2026-11-25T00:00:00", "value": None},
                    ]},
                }
            },
        }
        delta, state = build_daily_delta(payload, {})
        item = delta["symbols"]["SBER"]
        self.assertEqual(len(item["H1"]), 2)
        self.assertEqual(len(item["D1"]), 2)
        self.assertEqual(item["D1_value_missing"], 1)
        self.assertEqual(state["latest_h1"]["SBER"], "2026-11-25T11:00:00+00:00")
        self.assertEqual(state["latest_d1"]["SBER"], "2026-11-25")

    def test_second_snapshot_only_keeps_new_bars(self):
        payload = {
            "generated_at_utc": "2026-11-26T18:00:00+00:00",
            "timezone": "Europe/Moscow",
            "results": {
                "SBER": {
                    "H1": {"source": "Finam", "candles": [
                        {"timestamp": "2026-11-25T11:00:00+00:00"},
                        {"timestamp": "2026-11-26T10:00:00+00:00"},
                    ]},
                    "D1": {"source": "MOEX ISS TQBR history", "candles": [
                        {"timestamp": "2026-11-25T00:00:00", "value": 123456.0},
                        {"timestamp": "2026-11-26T00:00:00", "value": 234567.0},
                    ]},
                }
            },
        }
        state_in = {
            "latest_h1": {"SBER": "2026-11-25T11:00:00+00:00"},
            "latest_d1": {"SBER": "2026-11-25"},
        }
        delta, state = build_daily_delta(payload, state_in)
        self.assertEqual(len(delta["symbols"]["SBER"]["H1"]), 1)
        self.assertEqual(len(delta["symbols"]["SBER"]["D1"]), 1)
        self.assertEqual(state["latest_d1"]["SBER"], "2026-11-26")

    def test_no_new_bars_produces_empty_delta(self):
        payload = {
            "generated_at_utc": "2026-11-26T18:00:00+00:00",
            "timezone": "Europe/Moscow",
            "results": {
                "SBER": {
                    "H1": {"source": "Finam", "candles": [
                        {"timestamp": "2026-11-25T11:00:00+00:00"}]},
                    "D1": {"source": "MOEX ISS TQBR history", "candles": [
                        {"timestamp": "2026-11-25T00:00:00", "value": 123456.0}]},
                }
            },
        }
        state_in = {
            "latest_h1": {"SBER": "2026-11-25T11:00:00+00:00"},
            "latest_d1": {"SBER": "2026-11-25"},
        }
        delta, _ = build_daily_delta(payload, state_in)
        self.assertEqual(delta["symbols"], {})


if __name__ == "__main__":
    unittest.main()
