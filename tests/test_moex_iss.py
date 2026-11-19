import unittest
from urllib.parse import urlparse, parse_qs

from research_agent.moex_iss import fetch_candles, ISSDataError


def response(rows):
    return {"candles": {
        "columns": ["begin", "open", "close", "high", "low", "volume"],
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

        data = fetch_candles("sber", "2025-01-01", "2025-01-02",
                             getter=getter)
        self.assertEqual(len(data), 3)
        # A short non-empty page is not proof of completion; the loader
        # must request the next offset and stop only on an empty page.
        self.assertEqual(calls, ["0", "2", "3"])

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


if __name__ == "__main__":
    unittest.main()
