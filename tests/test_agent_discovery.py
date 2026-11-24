import io
import json
import unittest
import urllib.error

from research_agent.agent_discovery import (
    call_discovery_with_fallback,
    call_groq_discovery,
    call_openrouter_discovery,
    run_discovery,
)


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

    def test_groq_discovery_uses_compatible_request_profile(self):
        seen = {}
        payload = {"proposals": [], "strategy_hypotheses": []}

        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}).encode()

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["authorization"] = request.get_header("Authorization")
            seen["user_agent"] = request.get_header("User-agent")
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return Response()

        result = call_groq_discovery("synthetic probe", api_key="test-key", opener=opener)
        self.assertEqual(result, payload)
        self.assertEqual(seen["url"], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(seen["authorization"], "Bearer test-key")
        self.assertEqual(
            seen["user_agent"],
            "MOEX-EDGE-Research/1.0 (+https://github.com/vkazarin763-cloud/moex-edge-fast1)",
        )
        self.assertEqual(seen["body"]["reasoning_format"], "hidden")
        self.assertEqual(seen["body"]["reasoning_effort"], "low")
        self.assertEqual(seen["body"]["model"], "openai/gpt-oss-20b")
        self.assertEqual(seen["body"]["response_format"], __import__(
            "research_agent.agent_discovery", fromlist=["OUTPUT_SCHEMA"]
        ).OUTPUT_SCHEMA)

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


    def test_openrouter_uses_compatible_endpoint_and_parses_json(self):
        seen = {}
        payload = {"proposals": [], "strategy_hypotheses": []}

        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}).encode()

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["authorization"] = request.get_header("Authorization")
            seen["model"] = json.loads(request.data)["model"]
            return Response()

        result = call_openrouter_discovery(
            "probe", api_key="test-key", model="openrouter/free", opener=opener
        )
        self.assertEqual(result, payload)
        self.assertEqual(seen["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(seen["authorization"], "Bearer test-key")
        self.assertEqual(seen["model"], "openrouter/free")

    def test_openrouter_failure_falls_back_to_groq_and_preserves_provider_label(self):
        calls = []

        def openrouter(prompt, *, api_key, model):
            calls.append(("openrouter", api_key, model))
            raise RuntimeError("OpenRouter HTTP 429: rate limited")

        def groq(prompt, *, api_key, model):
            calls.append(("groq", api_key, model))
            return {"proposals": [], "strategy_hypotheses": []}

        result, provider = call_discovery_with_fallback(
            "probe",
            openrouter_api_key="openrouter-key",
            groq_api_key="groq-key",
            openrouter_caller=openrouter,
            groq_caller=groq,
        )
        self.assertEqual([item[0] for item in calls], ["openrouter", "groq"])
        self.assertEqual(calls[0], ("openrouter", "openrouter-key", "openrouter/free"))
        self.assertEqual(calls[1], ("groq", "groq-key", "openai/gpt-oss-20b"))
        self.assertEqual(provider, "groq_fallback")
        self.assertEqual(result["proposals"], [])

    def test_groq_only_path_uses_selected_groq_model_without_openrouter(self):
        calls = []

        def groq(prompt, *, api_key, model):
            calls.append((api_key, model))
            return {"proposals": [], "strategy_hypotheses": []}

        result, provider = call_discovery_with_fallback(
            "probe",
            openrouter_api_key="",
            groq_api_key="groq-key",
            groq_model="openai/gpt-oss-20b",
            groq_caller=groq,
        )
        self.assertEqual(provider, "groq_fallback")
        self.assertEqual(calls, [("groq-key", "openai/gpt-oss-20b")])
        self.assertEqual(result["proposals"], [])

    def test_both_provider_errors_are_preserved(self):
        def openrouter(prompt, *, api_key, model):
            raise RuntimeError("OpenRouter HTTP 401: invalid key")

        def groq(prompt, *, api_key, model):
            raise RuntimeError("Groq HTTP 403: model access denied")

        with self.assertRaisesRegex(
            RuntimeError, "OpenRouter HTTP 401.*Groq HTTP 403"
        ):
            call_discovery_with_fallback(
                "probe",
                openrouter_api_key="openrouter-key",
                groq_api_key="groq-key",
                openrouter_caller=openrouter,
                groq_caller=groq,
            )



if __name__ == "__main__":
    unittest.main()
