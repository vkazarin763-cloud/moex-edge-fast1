import unittest
from urllib.parse import urlparse, parse_qs

from research_agent.moex_iss import (
    fetch_candles, fetch_history_records, ISSDataError,
)


def response(rows):
    return {"candles": {
        "columns": ["begin", "open", "close", "high", "low", "volume"],
        "data": rows,
    }}


def history_response(rows, columns=None):
    return {"history": {
        "columns": columns or ["BOARDID", "TRADEDATE", "SECID", "NUMTRADES"],
        "data": rows,
    }}


class MOEXISSTests(unittest.TestCase):
    def test_paginates_and_preserves_rows(self):
        calls = []
        pages = [
            response([["2025-01-01 10:00:00", 100, 101, 102, 99, 1000],
                      ["2025-01-01 11:00:00", 101, 102, 103, 100, 1100]]),
            response([["2025-01-01 12:00:00", 102, 103, 104, 101, 1200]]),
            response([]),
        ]

        def getter(url, **kwargs):
            params = parse_qs(urlparse(url).query)
            calls.append(params["start"][0])
            self.assertNotIn("limit", params)
            return pages.pop(0)

        data = fetch_candles("sber", "2025-01-01", "2025-01-02", getter=getter)
        self.assertEqual(len(data), 3)
        self.assertEqual(calls, ["0", "2", "3"])

    def test_valid_weekend_session_candle_is_preserved(self):
        pages = [
            response([["2025-04-26 00:00:00", 100, 101, 102, 99, 1000]]),
            response([]),
        ]
        data = fetch_candles("AFKS", "2025-04-26", "2025-04-26",
                             getter=lambda *a, **k: pages.pop(0))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0].timestamp.weekday(), 5)

    def test_missing_columns_rejected(self):
        with self.assertRaises(ISSDataError):
            fetch_candles("SBER", "2025-01-01", "2025-01-02",
                          getter=lambda *a, **k: {"candles": {"columns": ["begin"], "data": []}})

    def test_duplicate_timestamps_rejected(self):
        page = response([["2025-01-01 10:00:00", 100, 101, 102, 99, 1000],
                         ["2025-01-01 10:00:00", 100, 101, 102, 99, 1000]])
        with self.assertRaises(ISSDataError):
            fetch_candles("SBER", "2025-01-01", "2025-01-02",
                          getter=lambda *a, **k: page)

    def test_history_paginates_and_preserves_zero_trade_rows(self):
        calls = []
        pages = [
            history_response([
                ["TQBR", "2025-01-02", "AMEZ", 0],
                ["TQBR", "2025-01-03", "AMEZ", 17],
            ]),
            history_response([]),
        ]

        def getter(url, **kwargs):
            params = parse_qs(urlparse(url).query)
            calls.append(params["start"][0])
            self.assertIn("/history/engines/stock/markets/shares/boards/TQBR/securities/AMEZ.json", url)
            self.assertEqual(params["tradingsession"], ["3"])
            return pages.pop(0)

        records = fetch_history_records("amez", "2025-01-01", "2025-01-31", getter=getter)
        self.assertEqual([(r.trade_date.isoformat(), r.num_trades) for r in records],
                         [("2025-01-02", 0), ("2025-01-03", 17)])
        self.assertEqual(calls, ["0", "2"])

    def test_history_parses_full_trading_day_ohlcv(self):
        columns = [
            "BOARDID", "TRADEDATE", "SECID", "NUMTRADES",
            "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME",
        ]
        page = history_response([[
            "TQBR", "2025-03-03", "SBER", 160752,
            309.84, 310.94, 300.20, 305.50, 69490830,
        ]], columns)
        records = fetch_history_records(
            "SBER", "2025-03-01", "2025-03-04",
            getter=lambda *a, **k: page,
        )
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(
            (record.open, record.high, record.low, record.close, record.volume),
            (309.84, 310.94, 300.20, 305.50, 69490830),
        )

    def test_history_missing_columns_rejected(self):
        with self.assertRaises(ISSDataError):
            fetch_history_records(
                "SBER", "2025-01-01", "2025-01-02",
                getter=lambda *a, **k: history_response([], ["TRADEDATE", "SECID"]),
            )

    def test_history_duplicate_dates_rejected(self):
        page = history_response([
            ["TQBR", "2025-01-02", "SBER", 1],
            ["TQBR", "2025-01-02", "SBER", 2],
        ])
        with self.assertRaises(ISSDataError):
            fetch_history_records("SBER", "2025-01-01", "2025-01-03",
                                  getter=lambda *a, **k: page)

    def test_history_rejects_out_of_range_and_negative_trade_count(self):
        outside = history_response([["TQBR", "2025-01-04", "SBER", 1]])
        with self.assertRaises(ISSDataError):
            fetch_history_records("SBER", "2025-01-01", "2025-01-03",
                                  getter=lambda *a, **k: outside)
        negative = history_response([["TQBR", "2025-01-02", "SBER", -1]])
        with self.assertRaises(ISSDataError):
            fetch_history_records("SBER", "2025-01-01", "2025-01-03",
                                  getter=lambda *a, **k: negative)


if __name__ == "__main__":
    unittest.main()
