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

    def test_validates_full_forecast_but_shares_only_candidate_forecasts_with_agents(self):
        forecasts = []
        for ticker in self.scan["universe"]:
            for horizon in (1, 5, 20):
                forecasts.append({
                    "ticker": ticker,
                    "horizon_sessions": horizon,
                    "status": "EXPERIMENTAL_NOT_CALIBRATED",
                    "model_version": "test-model-v1",
                    "post_holdout_outcomes_used": False,
                    "predicted_class": "UP",
                    "probability_down": 0.2,
                    "probability_sideways": 0.3,
                    "probability_up": 0.5,
                })
        forecast_report = {
            "report_type": "MOEX_EDGE_OPERATIONAL_DIRECTION_FORECAST_V1",
            "status": "COMPLETE",
            "model_version": "test-model-v1",
            "as_of_date": "2026-11-23",
            "holdout_policy": {
                "post_holdout_outcomes_used_for_training": 0,
                "post_holdout_outcomes_used_for_model_selection": 0,
                "post_holdout_outcomes_used_for_calibration": 0,
                "post_holdout_outcomes_used_for_performance_metrics": 0,
                "inference_parameters_frozen_before_holdout": True,
                "holdout_start": "2026-11-20",
            },
            "forecasts": forecasts,
        }
        prompts = []

        def fake(prompt, *, api_key, model):
            prompts.append(prompt)
            return {"proposals": [], "strategy_hypotheses": [], "forecast_reviews": []}

        _, diagnostics = run_discovery(
            self.scan, self.registry, api_key="fake", caller=fake,
            forecast_report=forecast_report,
        )
        self.assertEqual(len(prompts), 3)
        self.assertEqual(diagnostics["full_universe_forecast_rows_validated"], 6)
        self.assertEqual(diagnostics["forecast_symbols_shared_with_agents"], 1)
        for prompt in prompts:
            marker = "DETERMINISTIC SNAPSHOT: "
            self.assertIn(marker, prompt)
            snapshot = json.loads(prompt.split(marker, 1)[1])
            self.assertEqual(snapshot["universe"], ["SBER", "LKOH"])
            self.assertEqual(
                set(snapshot["direction_forecast"]["by_symbol"]),
                {"SBER"},
            )
            self.assertEqual(
                snapshot["direction_forecast"]["full_universe_forecast_rows_validated"],
                6,
            )
            self.assertEqual(
                snapshot["direction_forecast"]["candidate_symbols_shared_with_agents"],
                1,
            )

    def test_incomplete_full_universe_forecast_is_still_rejected(self):
        forecasts = []
        for ticker in self.scan["universe"]:
            for horizon in (1, 5, 20):
                forecasts.append({
                    "ticker": ticker,
                    "horizon_sessions": horizon,
                    "status": "EXPERIMENTAL_NOT_CALIBRATED",
                    "model_version": "test-model-v1",
                    "post_holdout_outcomes_used": False,
                    "predicted_class": "UP",
                    "probability_down": 0.2,
                    "probability_sideways": 0.3,
                    "probability_up": 0.5,
                })
        forecast_report = {
            "report_type": "MOEX_EDGE_OPERATIONAL_DIRECTION_FORECAST_V1",
            "status": "COMPLETE",
            "model_version": "test-model-v1",
            "holdout_policy": {
                "post_holdout_outcomes_used_for_training": 0,
                "post_holdout_outcomes_used_for_model_selection": 0,
                "post_holdout_outcomes_used_for_calibration": 0,
                "post_holdout_outcomes_used_for_performance_metrics": 0,
                "inference_parameters_frozen_before_holdout": True,
            },
            "forecasts": forecasts[:-1],
        }
        with self.assertRaisesRegex(ValueError, "all 1/5/20-session forecasts"):
            run_discovery(
                self.scan, self.registry, api_key="fake",
                caller=lambda prompt, **kwargs: {"proposals": [], "strategy_hypotheses": []},
                forecast_report=forecast_report,
            )

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
        payload = {"proposals": [], "strategy_hypotheses": [], "forecast_reviews": []}

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
        payload = {"proposals": [], "strategy_hypotheses": [], "forecast_reviews": []}

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



    def test_forecast_review_assessment_is_canonical_for_both_directions(self):
        self.scan["signals"].append({
            "symbol": "LKOH", "direction": "SHORT", "strategy": "Donchian20",
            "d1_bar_end_utc": "2026-11-20T21:00:00+00:00",
            "h1_confirmation": "CONFIRMED", "cross_strategy_conflict": False,
        })
        forecasts = []
        classes = {
            ("SBER", 1): "SIDEWAYS",
            ("SBER", 5): "UP",
            ("SBER", 20): "DOWN",
            ("LKOH", 1): "SIDEWAYS",
            ("LKOH", 5): "DOWN",
            ("LKOH", 20): "UP",
        }
        for ticker in self.scan["universe"]:
            for horizon in (1, 5, 20):
                predicted = classes[(ticker, horizon)]
                forecasts.append({
                    "ticker": ticker, "horizon_sessions": horizon,
                    "status": "EXPERIMENTAL_NOT_CALIBRATED",
                    "model_version": "test-model-v1",
                    "post_holdout_outcomes_used": False,
                    "predicted_class": predicted,
                    "probability_down": 0.2 if predicted != "DOWN" else 0.6,
                    "probability_sideways": 0.6 if predicted == "SIDEWAYS" else 0.2,
                    "probability_up": 0.6 if predicted == "UP" else 0.2,
                })
        forecast_report = {
            "report_type": "MOEX_EDGE_OPERATIONAL_DIRECTION_FORECAST_V1",
            "status": "COMPLETE", "model_version": "test-model-v1",
            "as_of_date": "2026-11-23",
            "holdout_policy": {
                "post_holdout_outcomes_used_for_training": 0,
                "post_holdout_outcomes_used_for_model_selection": 0,
                "post_holdout_outcomes_used_for_calibration": 0,
                "post_holdout_outcomes_used_for_performance_metrics": 0,
                "inference_parameters_frozen_before_holdout": True,
                "holdout_start": "2026-11-20",
            },
            "forecasts": forecasts,
        }
        calls = 0
        def fake(prompt, *, api_key, model):
            nonlocal calls
            calls += 1
            role_reviews = []
            # Each role reports a different assessment; canonical output must follow the model class.
            reported = {1: "AGREES", 2: "CONTRADICTS", 3: "NEUTRAL"}[calls]
            for ticker, direction, strategy, bar_end in [
                ("SBER", "LONG", "Donchian20", "2026-11-20T21:00:00+00:00"),
                ("LKOH", "SHORT", "Donchian20", "2026-11-20T21:00:00+00:00"),
            ]:
                for horizon in (1, 5, 20):
                    role_reviews.append({
                        "symbol": ticker, "direction": direction, "strategy": strategy,
                        "d1_bar_end_utc": bar_end, "horizon_sessions": horizon,
                        "assessment": reported, "rationale": f"raw rationale from role {calls}",
                    })
            return {"proposals": [], "strategy_hypotheses": [], "forecast_reviews": role_reviews}
        report, diagnostics = run_discovery(
            self.scan, self.registry, api_key="fake", caller=fake,
            forecast_report=forecast_report,
        )
        self.assertEqual(len(report["forecast_reviews"]), 18)
        by_key = {
            (row["symbol"], row["horizon_sessions"]): row
            for row in report["forecast_reviews"]
        }
        self.assertEqual(by_key[("SBER", 1)]["assessment"], "NEUTRAL")
        self.assertEqual(by_key[("LKOH", 1)]["assessment"], "NEUTRAL")
        self.assertEqual(by_key[("SBER", 5)]["assessment"], "AGREES")
        self.assertEqual(by_key[("SBER", 20)]["assessment"], "CONTRADICTS")
        self.assertEqual(by_key[("LKOH", 5)]["assessment"], "AGREES")
        self.assertEqual(by_key[("LKOH", 20)]["assessment"], "CONTRADICTS")
        self.assertTrue(by_key[("SBER", 1)]["assessment_corrected"])
        self.assertEqual(by_key[("SBER", 1)]["agent_reported_assessment"], "AGREES")
        self.assertEqual(by_key[("SBER", 1)]["agent_rationale"], "raw rationale from role 1")
        self.assertEqual(by_key[("SBER", 1)]["rationale"], "Класс SIDEWAYS не подтверждает ни LONG, ни SHORT.")
        self.assertEqual(diagnostics["forecast_review_conflicts"], [])
        self.assertEqual(len(diagnostics["forecast_review_agent_reported_conflicts"]), 6)
        self.assertEqual(diagnostics["forecast_review_corrections_count"], 12)
        self.assertEqual(diagnostics["forecast_review_corrections_by_role"], {
            "signal_hunter": 4, "strategy_scout": 4, "skeptical_reviewer": 4,
        })

if __name__ == "__main__":
    unittest.main()
