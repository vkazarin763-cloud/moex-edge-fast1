import unittest

from research_agent.price_forecast_24h.collector import (
    build_daily_delta, select_top_liquid, collect_selected_universe,
)


class CollectorDeltaTests(unittest.TestCase):
    def test_first_snapshot_keeps_available_history_and_marks_missing_value(self):
        payload = {
            "generated_at_utc": "2026-11-25T18:00:00+00:00",
            "timezone": "Europe/Moscow",
            "results": {"SBER": {
                "H1": {"source": "Finam", "candles": [
                    {"timestamp": "2026-11-25T10:00:00+00:00"},
                    {"timestamp": "2026-11-25T11:00:00+00:00"}]},
                "D1": {"source": "MOEX ISS TQBR history", "candles": [
                    {"timestamp": "2026-11-24T00:00:00", "value": 123456.0},
                    {"timestamp": "2026-11-25T00:00:00", "value": None}]}}}}
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
            "results": {"SBER": {
                "H1": {"source": "Finam", "candles": [
                    {"timestamp": "2026-11-25T11:00:00+00:00"},
                    {"timestamp": "2026-11-26T10:00:00+00:00"}]},
                "D1": {"source": "MOEX ISS TQBR history", "candles": [
                    {"timestamp": "2026-11-25T00:00:00", "value": 123456.0},
                    {"timestamp": "2026-11-26T00:00:00", "value": 234567.0}]}}}}
        state_in = {"latest_h1": {"SBER": "2026-11-25T11:00:00+00:00"},
                    "latest_d1": {"SBER": "2026-11-25"}}
        delta, state = build_daily_delta(payload, state_in)
        self.assertEqual(len(delta["symbols"]["SBER"]["H1"]), 1)
        self.assertEqual(len(delta["symbols"]["SBER"]["D1"]), 1)
        self.assertEqual(state["latest_d1"]["SBER"], "2026-11-26")

    def test_no_new_bars_produces_empty_delta(self):
        payload = {
            "generated_at_utc": "2026-11-26T18:00:00+00:00",
            "timezone": "Europe/Moscow",
            "results": {"SBER": {
                "H1": {"source": "Finam", "candles": [
                    {"timestamp": "2026-11-25T11:00:00+00:00"}]},
                "D1": {"source": "MOEX ISS TQBR history", "candles": [
                    {"timestamp": "2026-11-25T00:00:00", "value": 123456.0}]}}}}
        state_in = {"latest_h1": {"SBER": "2026-11-25T11:00:00+00:00"},
                    "latest_d1": {"SBER": "2026-11-25"}}
        delta, _ = build_daily_delta(payload, state_in)
        self.assertEqual(delta["symbols"], {})


class LiquiditySelectionTests(unittest.TestCase):
    @staticmethod
    def _rows(value, count=60):
        return [{"timestamp": f"2026-{i // 30 + 1:02d}-{i % 30 + 1:02d}T00:00:00",
                 "value": value} for i in range(count)]

    def test_selects_top_ten_by_official_value_not_all_44(self):
        results = {}
        for i in range(44):
            ticker = f"T{i:02d}"
            results[ticker] = {"D1": {
                "source": "MOEX ISS TQBR history", "status": "OK",
                "candles": self._rows((i + 1) * 1000)}}
        ranking = select_top_liquid({"results": results})
        self.assertEqual(len(ranking), 10)
        self.assertEqual([x["ticker"] for x in ranking],
                         [f"T{i:02d}" for i in range(43, 33, -1)])

    def test_missing_value_and_non_official_source_are_excluded(self):
        rows = self._rows(1000)
        for row in rows[:25]:
            row["value"] = None
        payload = {"results": {
            "TOO_FEW": {"D1": {"source": "MOEX ISS TQBR history", "status": "OK", "candles": rows}},
            "FINAM": {"D1": {"source": "Finam daily fallback", "status": "OK", "candles": self._rows(999999)}},
        }}
        self.assertEqual(select_top_liquid(payload), [])

    def test_ties_are_deterministic(self):
        rows = self._rows(1000)
        payload = {"results": {
            "ZZZ": {"D1": {"source": "MOEX ISS TQBR history", "status": "OK", "candles": rows}},
            "AAA": {"D1": {"source": "MOEX ISS TQBR history", "status": "OK", "candles": rows}},
        }}
        self.assertEqual([x["ticker"] for x in select_top_liquid(payload)],
                         ["AAA", "ZZZ"])

    def test_h1_collection_is_requested_only_for_selected_tickers(self):
        calls = []
        candidates = [f"T{i:02d}" for i in range(44)]
        d1_results = {ticker: {"D1": {
            "source": "MOEX ISS TQBR history", "status": "OK",
            "candles": self._rows((i + 1) * 1000)}}
            for i, ticker in enumerate(candidates)}
        def fake_collector(tickers, **kwargs):
            calls.append((list(tickers), kwargs["frames"]))
            if kwargs["frames"] == ("D1",):
                return {"generated_at_utc": "2026-11-25T18:00:00+00:00",
                        "timezone": "Europe/Moscow", "results": d1_results}
            return {"results": {ticker: {"H1": {"source": "Finam", "status": "OK", "candles": []}}
                                for ticker in tickers}}
        payload = collect_selected_universe(candidates, api_token="test", collector=fake_collector)
        self.assertEqual(len(calls[0][0]), 44)
        self.assertEqual(calls[0][1], ("D1",))
        self.assertEqual(len(calls[1][0]), 10)
        self.assertEqual(calls[1][1], ("H1", "D1"))
        self.assertEqual(payload["liquidity_selection"]["selected_count"], 10)
        self.assertEqual(len(payload["results"]), 44)


if __name__ == "__main__":
    unittest.main()
