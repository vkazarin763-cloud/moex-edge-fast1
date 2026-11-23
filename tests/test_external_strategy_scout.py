import unittest
from research_agent.external_strategy_scout import discover, _market_evidence, _candidate_type, _base_record

class ScoutTests(unittest.TestCase):
    def test_market_tags_come_from_result_evidence_not_query(self):
        self.assertEqual(_market_evidence("A strategy for crude oil futures"), ["futures"])
        self.assertEqual(_market_evidence("A stock screener and equity strategy"), ["equities"])
        self.assertEqual(_market_evidence("Generic backtesting toolkit"), [])
        self.assertEqual(_market_evidence("ETH perpetual futures options"), ["futures", "options"])

    def test_repository_topics_contribute_market_evidence(self):
        item = _base_record("github_repository", "systematic trading", "https://github.com/demo/x", topics=["options", "futures"])
        self.assertEqual(item["market_tags"], ["futures", "options"])

    def test_infrastructure_is_not_mislabeled_as_strategy(self):
        self.assertEqual(_candidate_type("Backtesting engine for systematic research", "github_repository"), "INFRASTRUCTURE_OR_EDUCATION")
        self.assertEqual(_candidate_type("Daily momentum trading strategy", "github_repository"), "POSSIBLE_STRATEGY_IMPLEMENTATION")

    def test_collects_provenance_and_deduplicates(self):
        calls = []
        def fake_fetch(url):
            calls.append(url)
            if "api.github.com/search/repositories" in url:
                return {"items": [
                    {"full_name": "demo/equity-strategy", "html_url": "https://github.com/demo/equity-strategy", "owner": {"login": "demo"}, "description": "Daily stock momentum strategy", "license": {"spdx_id": "MIT"}, "stargazers_count": 12, "pushed_at": "2026-01-01T00:00:00Z"}
                ]}
            return {"message": {"items": [
                {"title": ["Oil futures trading strategy"], "URL": "https://doi.org/10.0000/demo", "DOI": "10.0000/demo", "author": [{"given": "A", "family": "Author"}], "published": {"date-parts": [[2024]]}}
            ]}}
        report = discover(limit=2, fetcher=fake_fetch, pause_seconds=0)
        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(report['markets'], ['equities'])
        self.assertIn('equity', calls[0])
        self.assertNotIn('in%3Areadme', calls[1])
        self.assertEqual(report["schema_version"], "1.1")
        self.assertEqual(report["mode"], "METADATA_ONLY_NO_MARKET_DATA_NO_SIGNALS_NO_BACKTEST")
        by_title = {x["title"]: x for x in report["candidates"]}
        self.assertEqual(by_title["demo/equity-strategy"]["market_tags"], ["equities"])
        self.assertNotIn("Oil futures trading strategy", by_title)
        self.assertEqual(by_title["demo/equity-strategy"]["query_market"], "equities")
        self.assertIsNotNone(by_title["demo/equity-strategy"]["candidate_id"])
        self.assertTrue(all(x["evidence_status"] == "SOURCE_LEAD_ONLY_RULES_NOT_REVIEWED" for x in report["candidates"]))

    def test_invalid_limit_rejected(self):
        with self.assertRaises(ValueError):
            discover(limit=0, fetcher=lambda _: {}, pause_seconds=0)

    def test_source_failures_are_reported_not_hidden(self):
        report = discover(limit=1, fetcher=lambda _: (_ for _ in ()).throw(OSError("offline")), pause_seconds=0)
        self.assertEqual(report["candidate_count"], 0)
        self.assertEqual(len(report["errors"]), 2)
        self.assertEqual(report["status"], "NO_SOURCES_FOUND")

if __name__ == "__main__":
    unittest.main()
