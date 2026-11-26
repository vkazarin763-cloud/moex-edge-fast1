import unittest
from research_agent.fundamentals.collector import normalize_report, collect, UNIVERSE


class FundamentalsCollectorTests(unittest.TestCase):
    def test_normalize_preserves_period_and_publication_separately(self):
        row = {
            "SECID": "SBER",
            "REPORT_TYPE": "IFRS annual",
            "PUBLISH_DATE": "2026-03-20T10:00:00",
            "PERIOD_END": "2025-12-31",
            "URL": "https://example.test/report.pdf",
        }
        item = normalize_report(row)
        self.assertEqual(item["ticker"], "SBER")
        self.assertEqual(item["publication_timestamp"], "2026-03-20T10:00:00")
        self.assertEqual(item["reporting_period_end"], "2025-12-31")
        self.assertEqual(item["raw"], row)

    def test_collector_keeps_unmatched_rows_and_reports_source_status(self):
        def fake_getter(url):
            if url.endswith("/companies.json"):
                return {"cci_company": {"columns": ["basis_company_id", "short_name"],
                                        "data": [[123, "Example"]]}}
            return {"cci_corp_info": {"columns": ["basis_company_id", "secid", "title"],
                                      "data": [[123, "SBER", "Annual report"],
                                               [456, None, "Unknown issuer"]]}}
        result = collect(fake_getter)
        self.assertEqual(result["source_access"]["companies"], "ok")
        self.assertEqual(result["source_access"]["reports"], "ok")
        self.assertEqual(len(result["reports_by_ticker"]["SBER"]), 1)
        self.assertEqual(len(result["unmatched_reports"]), 1)
        self.assertEqual(result["coverage"]["universe_size"], len(UNIVERSE))

    def test_missing_publication_date_stays_null(self):
        item = normalize_report({"period_end": "2025-12-31"})
        self.assertIsNone(item["publication_timestamp"])
        self.assertEqual(item["reporting_period_end"], "2025-12-31")


if __name__ == "__main__":
    unittest.main()
