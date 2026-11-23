import unittest
from research_agent.external_strategy_scout import discover

class ScoutTests(unittest.TestCase):
    def test_collects_and_deduplicates_public_source_metadata(self):
        calls = []
        def fake_fetch(url):
            calls.append(url)
            if "api.github.com/search/repositories" in url:
                return {"items": [{"full_name": "demo/strategy", "html_url": "https://github.com/demo/strategy", "owner": {"login": "demo"}, "license": {"spdx_id": "MIT"}, "stargazers_count": 12}] }
            return {"message": {"items": [{"title": ["A paper"], "URL": "https://doi.org/10.0000/demo", "DOI": "10.0000/demo", "author": [{"given": "A", "family": "Author"}], "published": {"date-parts": [[2024]]}}]}}
        report = discover(limit=2, fetcher=fake_fetch, pause_seconds=0)
        self.assertEqual(report["candidate_count"], 2)
        self.assertEqual(len(calls), 6)
        self.assertEqual(report["mode"], "METADATA_ONLY_NO_MARKET_DATA_NO_SIGNALS_NO_BACKTEST")
        self.assertTrue(all(x["evidence_status"] == "SOURCE_LEAD_ONLY_RULES_NOT_REVIEWED" for x in report["candidates"]))

    def test_invalid_limit_rejected(self):
        with self.assertRaises(ValueError):
            discover(limit=0, fetcher=lambda _: {}, pause_seconds=0)

    def test_source_failures_are_reported_not_hidden(self):
        report = discover(limit=1, fetcher=lambda _: (_ for _ in ()).throw(OSError("offline")), pause_seconds=0)
        self.assertEqual(report["candidate_count"], 0)
        self.assertEqual(len(report["errors"]), 6)
        self.assertEqual(report["status"], "NO_SOURCES_FOUND")

if __name__ == "__main__":
    unittest.main()