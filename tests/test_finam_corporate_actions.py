"""Tests for read-only Finam corporate-action event retrieval."""
import unittest
from datetime import date
from urllib.parse import urlparse, parse_qs

from research_agent.finam_corporate_actions import (
    fetch_event_pages, fetch_instrument_corporate_actions,
)


class CorporateActionFetchTests(unittest.TestCase):
    def test_paginates_until_terminal_page_and_preserves_dotted_query_keys(self):
        calls = []
        def requester(url, token):
            calls.append((url, token))
            offset = int(parse_qs(urlparse(url).query)["offset"][0])
            if offset == 0:
                return {"dividends": [{"date": {"year": 2025, "month": 1, "day": 1}}],
                        "pagination": {"has_next": True}}
            return {"dividends": [{"date": {"year": 2025, "month": 2, "day": 1}}],
                    "pagination": {"has_next": False}}
        result = fetch_event_pages(
            "SBER@MISX", "/v1/past-dividends", "dividends", "test-token",
            date(2021, 1, 1), date(2026, 1, 1), requester=requester, page_size=1,
        )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call[1] == "test-token" for call in calls))
        self.assertIn("date_from.year=2021", calls[0][0])
        self.assertNotIn("date_from%2Eyear", calls[0][0])

    def test_fund_does_not_request_split_endpoint(self):
        calls = []
        def requester(url, token):
            calls.append(url)
            return {"dividends": [], "pagination": {"has_next": False}}
        result = fetch_instrument_corporate_actions(
            "SBMM@MISX", "fund", "token", date(2021, 1, 1), date(2026, 1, 1),
            requester=requester,
        )
        self.assertEqual(len(calls), 1)
        self.assertIn("/v1/past-dividends?", calls[0])
        self.assertEqual(result["splits"]["status"], "NOT_APPLICABLE")
        self.assertIn("RECORD_DATE", result["adjustment_status"])

    def test_equity_requests_dividends_and_splits(self):
        calls = []
        def requester(url, token):
            calls.append(url)
            key = "splits" if "/splits/past" in url else "dividends"
            return {key: [], "pagination": {"has_next": False}}
        result = fetch_instrument_corporate_actions(
            "SBER@MISX", "equity", "token", date(2021, 1, 1), date(2026, 1, 1),
            requester=requester,
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["dividends"]["status"], "OK")
        self.assertEqual(result["splits"]["status"], "OK")

    def test_request_failure_is_sanitized(self):
        def requester(url, token):
            raise RuntimeError("HTTP_403: sensitive response body")
        result = fetch_event_pages(
            "SBER@MISX", "/v1/past-dividends", "dividends", "token",
            date(2021, 1, 1), date(2026, 1, 1), requester=requester,
        )
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["error_code"], "HTTP_403")
        self.assertNotIn("sensitive", str(result))

    def test_invalid_endpoint_rejected(self):
        with self.assertRaises(ValueError):
            fetch_event_pages(
                "SBER@MISX", "/v1/orders", "orders", "token",
                date(2021, 1, 1), date(2026, 1, 1), requester=lambda *_: {},
            )


if __name__ == "__main__":
    unittest.main()
