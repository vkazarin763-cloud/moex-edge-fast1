import json
import unittest

from research_agent.agent_discovery import call_groq_discovery, run_discovery


class AgentDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.scan = {
            "status": "READ_ONLY_LATEST_SIGNAL_SCAN",
            "generated_at_utc": "2026-11-23T12:00:00+00:00",
            "as_of_utc": "2026-11-23T12:00:00+00:00",
            "universe": ["SBER", "LKOH"],
            "signals": [{
                "symbol": "SBER", "direction": "LONG", "strategy": "Donchian20",
                "d1_bar_end_utc": "2026-11-20T21:00:00+00:00",
                "h1_confirmation": "CONFIRMED", "cross_strategy_conflict": False,
            }],
        }
        self.registry = {
            "registry_version": "test",
            "summary": {"PASS": 0, "REJECT": 1, "INSUFFICIENT_DATA": 9},
            "strategies": [{
                "ticker": "SBER", "direction": "LONG", "strategy": "Donchian20",
                "status": "INSUFFICIENT_DATA", "eligible_for_shadow_scanner": False,
            }],
            "stage": "DEVELOPMENT_ONLY_NOT_PRODUCTION_APPROVAL",
            "source_report_date_till": "2026-11-20",
            "holdout_used_for_selection": False,
            "scanner_contract": {"consume_only_status": "PASS", "live_trading_authorized": False},
        }

    def test_http_permission_error_preserves_provider_diagnostic(self):
        body = json.dumps({
            "error": {
                "message": "The model is blocked at the organization level.",
                "type": "permissions_error",
                "code": "model_permission_blocked_org",
            }
        }).encode("utf-8")

        def denied(*args, **kwargs):
            raise urllib.error.HTTPError(
                "https://api.groq.com/openai/v1/chat/completions",
                403, "Forbidden", {}, io.BytesIO(body),
            )

        with self.assertRaisesRegex(
            RuntimeError, "HTTP 403.*model_permission_blocked_org.*blocked at the organization level"
        ):
            call_groq_discovery("probe", api_key="fake", opener=denied)

    def test_two_of_three_consensus_and_experimental_verification(self):
        candidate = {
            "symbol": "SBER", "direction": "LONG", "strategy": "Donchian20",
            "d1_bar_end_utc": "2026-11-20T21:00:00+00:00",
            "rationale": "Candidate selected from scan.",
        }
        idea = {
            "strategy": "Donchian20", "direction": "LONG", "timeframe_config": "A",
            "hypothesis": "A breakout family may merit further study.",
            "research_question": "Does the weekly context improve robustness?",
        }
        calls = []
        def fake(prompt, *, api_key, model):
            calls.append(prompt)
            index = len(calls)
            return {
                "proposals": [candidate] if index < 3 else [],
                "strategy_hypotheses": [idea] if index < 3 else [],
            }
        report, diagnostics = run_discovery(self.scan, self.registry, api_key="fake", caller=fake)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(report["proposals"]), 1)
        self.assertEqual(diagnostics["hypothesis_count"], 1)
        self.assertEqual(diagnostics["consensus_proposal_count"], 1)
        self.assertEqual(diagnostics["strategy_hypotheses"][0]["status"], "UNTESTED_RESEARCH_HYPOTHESIS")
        from research_agent.agent_signal_verifier import verify_agent_proposals
        checked = verify_agent_proposals(report, self.scan, self.registry)
        self.assertEqual(checked["results"][0]["status"], "EXPERIMENTAL_STRATEGY_UNAPPROVED")
        self.assertEqual(checked["confirmed_signals_count"], 0)

    def test_agent_cannot_inject_a_nonexistent_candidate(self):
        invalid = {
            "symbol": "GAZP", "direction": "LONG", "strategy": "Donchian20",
            "d1_bar_end_utc": "2026-11-20T21:00:00+00:00", "rationale": "invented",
        }
        def fake(prompt, *, api_key, model):
            return {"proposals": [invalid], "strategy_hypotheses": []}
        report, diagnostics = run_discovery(self.scan, self.registry, api_key="fake", caller=fake)
        self.assertEqual(report["proposals"], [])
        self.assertEqual(diagnostics["unmatched_or_invalid_proposals"]["signal_hunter"], 1)



    def test_numeric_claims_in_unverified_hypotheses_are_dropped(self):
        idea = {
            "strategy": "Donchian20", "direction": "LONG", "timeframe_config": "A",
            "hypothesis": "This setup has a 90 percent win rate.",
            "research_question": "Should it be tested?",
        }
        def fake(prompt, *, api_key, model):
            return {"proposals": [], "strategy_hypotheses": [idea]}
        report, diagnostics = run_discovery(self.scan, self.registry, api_key="fake", caller=fake)
        self.assertEqual(diagnostics["hypothesis_count"], 0)

    def test_duplicate_rows_from_one_agent_do_not_fake_consensus(self):
        candidate = {
            "symbol": "SBER", "direction": "LONG", "strategy": "Donchian20",
            "d1_bar_end_utc": "2026-11-20T21:00:00+00:00", "rationale": "candidate",
        }
        calls = 0
        def fake(prompt, *, api_key, model):
            nonlocal calls
            calls += 1
            return {"proposals": [candidate, candidate] if calls == 1 else [], "strategy_hypotheses": []}
        report, diagnostics = run_discovery(self.scan, self.registry, api_key="fake", caller=fake)
        self.assertEqual(report["proposals"], [])
        self.assertEqual(diagnostics["consensus_proposal_count"], 0)

    def test_no_consensus_means_no_signal_proposal(self):
        candidate = {
            "symbol": "SBER", "direction": "LONG", "strategy": "Donchian20",
            "d1_bar_end_utc": "2026-11-20T21:00:00+00:00", "rationale": "candidate",
        }
        count = 0
        def fake(prompt, *, api_key, model):
            nonlocal count
            count += 1
            return {"proposals": [candidate] if count == 1 else [], "strategy_hypotheses": []}
        report, diagnostics = run_discovery(self.scan, self.registry, api_key="fake", caller=fake)
        self.assertEqual(report["proposals"], [])
        self.assertEqual(diagnostics["consensus_proposal_count"], 0)


if __name__ == "__main__":
    unittest.main()
