import unittest
from datetime import datetime, timezone

from research_agent.finam_screener_adapter import (
    FINAM_IDS,
    TICKERS,
    FinamScreenerDataError,
    build_screener_requests,
    normalize_screener_responses,
)


def make_responses():
    responses = []
    for request in build_screener_requests():
        rows = []
        for security_id in request["ids"]:
            ticker = next(name for name, value in FINAM_IDS.items() if value == security_id)
            rows.append({
                "asset": {"security_id": security_id, "ticker": ticker, "market": 2},
                "quote_last": 123.45,
                "market_capitalization": 1000000,
                "pe_ratio": None,
                "dividend_yield_12m": 0.1345,
            })
        responses.append({"data": rows, "has_next": False})
    return responses


class FinamScreenerAdapterTests(unittest.TestCase):
    def test_frozen_universe_has_44_unique_tickers_and_ids(self):
        self.assertEqual(len(TICKERS), 44)
        self.assertEqual(len(set(TICKERS)), 44)
        self.assertEqual(len(set(FINAM_IDS.values())), 44)

    def test_requests_are_batched_for_only_the_frozen_universe(self):
        requests = build_screener_requests()
        self.assertEqual([len(item["ids"]) for item in requests], [10, 10, 10, 10, 4])
        self.assertEqual(sum(len(item["ids"]) for item in requests), 44)
        self.assertTrue(all(item["market"] == 2 for item in requests))
        self.assertTrue(all(item["limit"] == 10 for item in requests))
        self.assertTrue(all(item["asset_class"] == "stock" for item in requests))

    def test_normalizes_44_rows_and_keeps_quote_freshness_unknown(self):
        result = normalize_screener_responses(
            make_responses(),
            retrieved_at=datetime(2026, 11, 22, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(result["received_count"], 44)
        self.assertEqual(result["missing_tickers"], [])
        self.assertEqual(result["quote_freshness"], "UNKNOWN")
        sber = next(row for row in result["records"] if row["ticker"] == "SBER")
        self.assertAlmostEqual(sber["dividend_yield_12m_fraction"], 0.1345)
        self.assertAlmostEqual(sber["dividend_yield_12m_percent"], 13.45)
        self.assertIsNone(sber["quote_timestamp_utc"])
        self.assertEqual(sber["quote_freshness"], "UNKNOWN_NO_PROVIDER_QUOTE_TIMESTAMP")

    def test_null_metric_is_preserved(self):
        responses = make_responses()
        responses[0]["data"][0]["dividend_yield_12m"] = None
        result = normalize_screener_responses(responses, retrieved_at="2026-11-22T12:00:00Z")
        self.assertIsNone(result["records"][0]["dividend_yield_12m_percent"])

    def test_missing_ticker_fails_closed(self):
        responses = make_responses()
        responses[-1]["data"].pop()
        with self.assertRaisesRegex(FinamScreenerDataError, "missing tickers"):
            normalize_screener_responses(responses, retrieved_at="2026-11-22T12:00:00Z")

    def test_duplicate_row_fails_closed(self):
        responses = make_responses()
        responses[1]["data"].append(responses[0]["data"][0])
        with self.assertRaisesRegex(FinamScreenerDataError, "duplicate"):
            normalize_screener_responses(responses, retrieved_at="2026-11-22T12:00:00Z")

    def test_unknown_id_fails_closed(self):
        responses = make_responses()
        responses[0]["data"][0]["asset"]["security_id"] = 999999
        with self.assertRaisesRegex(FinamScreenerDataError, "unexpected Finam"):
            normalize_screener_responses(responses, retrieved_at="2026-11-22T12:00:00Z")

    def test_ticker_id_mismatch_fails_closed(self):
        responses = make_responses()
        responses[0]["data"][0]["asset"]["ticker"] = "SBER"
        with self.assertRaisesRegex(FinamScreenerDataError, "ticker/ID mismatch"):
            normalize_screener_responses(responses, retrieved_at="2026-11-22T12:00:00Z")

    def test_non_finite_values_fail_closed(self):
        responses = make_responses()
        responses[0]["data"][0]["quote_last"] = float("nan")
        with self.assertRaisesRegex(FinamScreenerDataError, "finite"):
            normalize_screener_responses(responses, retrieved_at="2026-11-22T12:00:00Z")

    def test_naive_retrieval_timestamp_is_rejected(self):
        with self.assertRaisesRegex(FinamScreenerDataError, "timezone"):
            normalize_screener_responses(make_responses(), retrieved_at="2026-11-22T12:00:00")

    def test_missing_quote_price_fails_closed(self):
        responses = make_responses()
        responses[0]["data"][0]["quote_last"] = None
        with self.assertRaisesRegex(FinamScreenerDataError, "must be numeric"):
            normalize_screener_responses(responses, retrieved_at="2026-11-22T12:00:00Z")

    def test_unconsumed_pagination_fails_closed(self):
        responses = make_responses()
        responses[0]["has_next"] = True
        with self.assertRaisesRegex(FinamScreenerDataError, "another page"):
            normalize_screener_responses(responses, retrieved_at="2026-11-22T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
