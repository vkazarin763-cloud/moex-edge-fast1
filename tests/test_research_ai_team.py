"""Offline tests for the optional multi-provider research team."""
import json
import unittest

from research_agent.ai_team import (
    DEFAULT_MODEL,
    DEFAULT_GROQ_MODEL,
    MAX_INPUT_CHARS,
    SYSTEM_PROMPT,
    _compact_report,
    _extract_text,
    call_groq,
    call_provider,
    run_team,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class AITeamTests(unittest.TestCase):
    def test_ai_instructions_distinguish_holdout_family_from_directional_registry(self):
        self.assertIn("does not split LONG/SHORT", SYSTEM_PROMPT)
        self.assertIn("never compare its row count directly", SYSTEM_PROMPT)

    def test_compact_report_preserves_session_reconciliation_and_history_crosscheck(self):
        source = {
            "results": {
                "SBER": {
                    "status": "ANALYZED",
                    "session_date_mapping": {
                        "status": "RECONCILIATION_WITH_CAVEATS",
                        "trading_days_reconciled": 764,
                        "trading_days_mismatched": 1,
                        "mismatch_field_counts": {"volume": 1},
                        "mismatch_examples": [{
                            "trade_date": "2025-08-01",
                            "differences": {"volume": {"aggregated": 25320049, "history": 18473506}},
                        }],
                        "unassigned_raw_candles": 0,
                        "raw_history_coverage_status": "COMPLETE_DATE_COVERAGE",
                        "raw_history_date_coverage_ratio": 1.0,
                    },
                    "tqbr_history_crosscheck": {
                        "status": "NO_MISSING_CANDLE_DETECTED_ON_RECORDED_TRADE_DATES",
                        "missing_candles_on_trade_dates": [],
                        "zero_trade_sessions_without_candles": [],
                        "candles_present_on_zero_trade_dates": [],
                        "history_rows_unknown_trade_count": [],
                        "candles_without_history_record": [],
                        "mapped_weekend_fragments_without_same_date_history": 138,
                        "weekend_fragments_excluded_from_same_date_crosscheck": True,
                        "mapped_weekday_additional_session_fragments_without_same_date_history": 4,
                        "weekday_additional_session_fragments_excluded_from_same_date_crosscheck": True,
                    },
                }
            }
        }
        compact = json.loads(_compact_report(source))
        row = compact["results"]["SBER"]
        self.assertEqual(compact["schema"]["status_codes"][row["m"]["s"]], "RECONCILIATION_WITH_CAVEATS")
        self.assertEqual(row["m"]["trading_days_mismatched"], 1)
        self.assertEqual(row["m"]["mismatch_examples"][0]["differences"]["volume"]["aggregated"], 25320049)
        self.assertEqual(compact["schema"]["status_codes"][row["h"]["s"]], "NO_MISSING_CANDLE_DETECTED_ON_RECORDED_TRADE_DATES")
        self.assertEqual(row["h"]["mapped_weekend_fragments_without_same_date_history"], 138)
        self.assertTrue(row["h"]["weekend_fragments_excluded_from_same_date_crosscheck"])
        self.assertEqual(row["h"]["mapped_weekday_additional_session_fragments_without_same_date_history"], 4)
        self.assertTrue(row["h"]["weekday_additional_session_fragments_excluded_from_same_date_crosscheck"])
        self.assertEqual(row["h"]["candles_without_history_record"], 0)

    def test_compact_report_drops_raw_history_and_trade_ledgers(self):
        source = {
            "date_from": "2023-01-01",
            "results": {
                "SBER": {
                    "status": "ANALYZED",
                    "candles": 700,
                    "walk_forward": {
                        "candidates": {"Donchian20": {"closed_trades": 42}},
                        "folds": [{"trade_ledger": [{"entry_price": 1}] * 500}],
                    },
                    "raw_candles": [{"close": 1}] * 500,
                }
            },
            "raw_history": "x" * (MAX_INPUT_CHARS * 2),
        }
        compact = json.loads(_compact_report(source))
        self.assertEqual(compact["results"]["SBER"]["b"], 700)
        self.assertEqual(
            compact["results"]["SBER"]["w"]["D20"][1],
            42,
        )
        self.assertNotIn("raw_history", compact)
        self.assertNotIn("trade_ledger", json.dumps(compact))
        self.assertLessEqual(len(_compact_report(source)), MAX_INPUT_CHARS)

    def test_large_report_projection_preserves_compact_evidence_and_all_tickers(self):
        strategies = {
            "Donchian20": {
                "status": "REJECT_OR_INSUFFICIENT_EVIDENCE",
                "closed_trades": 17,
                "average_net_return": -0.00125,
                "folds": [{"trade_ledger": [{"price": 1}] * 1000}] * 20,
            }
        }
        source = {
            "generated_at_utc": "2026-11-22T00:00:00Z",
            "universe": {"count": 44},
            "independent_validation": {"status": "CHECKED"},
            "cross_sectional_direction_summary": {"LONG": {"count": 44}},
            "results": {
                **{
                    f"T{i:02d}": {
                        "status": "ANALYZED",
                        "candles": 500,
                        "research_input_bars": 480,
                        "data_quality": {
                            "status": "VALID_WITH_CAVEATS",
                            "out_of_range_bars": 0,
                            "calendar_gap_count": 3,
                            "exchange_calendar_verified": False,
                        },
                        "walk_forward": {"candidates": strategies},
                        "raw_candles": [{"close": 1}] * 5000,
                    }
                    for i in range(43)
                },
                "T": {
                    "status": "INSUFFICIENT_POST_ACTION_HISTORY",
                    "research_input_bars": 12,
                },
            },
            "development_portfolio": {
                "candidate_trades": [{"trade_ledger": [1] * 1000}] * 100,
                "continuous_development_replay": {"history": [1] * 10000},
            },
        }
        compact_text = _compact_report(source)
        compact = json.loads(compact_text)
        self.assertLessEqual(len(compact_text), MAX_INPUT_CHARS)
        self.assertEqual(len(compact["results"]), 44)
        self.assertEqual(compact["schema"]["status_codes"][compact["results"]["T"]["s"]], "INSUFFICIENT_POST_ACTION_HISTORY")
        metric = compact["results"]["T00"]["w"]["D20"]
        self.assertEqual(metric[1], 17)
        self.assertEqual(metric[2], -0.00125)
        self.assertIn("independent_validation", compact)
        self.assertNotIn("raw_candles", compact_text)
        self.assertNotIn("trade_ledger", compact_text)
        self.assertNotIn("continuous_development_replay", compact_text)

    def test_oversized_descriptive_metadata_is_reduced_without_dropping_registry(self):
        registry_rows = [
            {
                "ticker": f"T{i:02d}", "direction": direction, "strategy": "Donchian20",
                "status": "INSUFFICIENT_DATA", "reasons": ["sample below threshold"],
                "closed_trades": 12, "average_net_return": 0.01,
                "profit_factor": 1.2, "positive_folds": 1,
                "adequately_sampled_folds": 1, "folds": 4,
                "double_cost_average_net_return": 0.005,
                "eligible_for_shadow_scanner": False,
            }
            for i in range(25) for direction in ("LONG", "SHORT")
        ]
        report = {
            "generated_at_utc": "2026-11-23T00:00:00Z",
            "date_till": "2026-11-20",
            "results": {
                f"T{i:02d}": {
                    "status": "ANALYZED",
                    "adversarial_cost_check": {
                        "baseline_execution_config": {"fee_per_side": 0.001},
                        "double_cost_execution_config": {"fee_per_side": 0.002},
                    },
                }
                for i in range(25)
            },
            "cross_sectional_direction_summary": {f"verbose_metric_{i}": i for i in range(1200)},
            "experiment_lab": {f"verbose_experiment_{i}": i for i in range(1200)},
            "independent_validation": {"status": "INDEPENDENT_VALIDATION_INCOMPLETE", "checks": 55, "errors": 0},
        }
        registry = {
            "registry_version": "development-registry-v1",
            "stage": "DEVELOPMENT_ONLY_NOT_PRODUCTION_APPROVAL",
            "summary": {"PASS": 0, "REJECT": 0, "INSUFFICIENT_DATA": 50},
            "strategies": registry_rows,
        }
        compact_text = _compact_report(report, registry=registry)
        compact = json.loads(compact_text)
        self.assertLessEqual(len(compact_text), MAX_INPUT_CHARS)
        self.assertEqual(len(compact["strategy_registry"]["strategies"]), 50)
        self.assertEqual(len(compact["results"]), 25)
        self.assertEqual(compact["strategy_registry"]["summary"]["INSUFFICIENT_DATA"], 50)
        self.assertFalse(compact["strategy_registry"]["strategies"][0]["eligible_for_shadow_scanner"])
        self.assertEqual(
            compact["cost_model_by_ticker"]["T00"]["double_cost_execution_config"]["fee_per_side"],
            0.002,
        )
        self.assertEqual(
            compact["independent_validation"]["status"],
            "INDEPENDENT_VALIDATION_INCOMPLETE",
        )
        self.assertIn("omitted", compact["experiment_lab"]["detail"].lower())

    def test_compact_report_includes_authoritative_directional_registry_and_costs(self):
        report = {
            "generated_at_utc": "2026-11-23T00:00:00Z",
            "date_till": "2026-11-20",
            "results": {
                "GAZP": {
                    "status": "ANALYZED",
                    "adversarial_cost_check": {
                        "stress": "2x entry/exit fees and slippage",
                        "baseline_execution_config": {
                            "fee_per_side": 0.001, "slippage_per_side": 0.0005,
                            "stop_pct": 0.03, "target_pct": 0.06, "max_bars": 120,
                        },
                        "double_cost_execution_config": {
                            "fee_per_side": 0.002, "slippage_per_side": 0.001,
                            "stop_pct": 0.03, "target_pct": 0.06, "max_bars": 120,
                        },
                    },
                }
            },
        }
        registry = {
            "registry_version": "development-registry-v1",
            "stage": "DEVELOPMENT_ONLY_NOT_PRODUCTION_APPROVAL",
            "source_report_generated_at_utc": "2026-11-23T00:00:00Z",
            "source_report_date_till": "2026-11-20",
            "summary": {"PASS": 0, "REJECT": 0, "INSUFFICIENT_DATA": 2},
            "selection_policy": {"minimum_closed_trades": 30},
            "scanner_contract": {"live_trading_authorized": False},
            "strategies": [
                {
                    "ticker": "GAZP", "direction": "LONG", "strategy": "Donchian20",
                    "status": "INSUFFICIENT_DATA",
                    "reasons": ["Only 17 closed trades; minimum is 30"],
                    "closed_trades": 17, "average_net_return": 0.0098,
                    "profit_factor": 1.57, "positive_folds": 3,
                    "adequately_sampled_folds": 2, "folds": 4,
                    "double_cost_average_net_return": 0.0073,
                    "eligible_for_shadow_scanner": False,
                },
                {
                    "ticker": "GAZP", "direction": "SHORT", "strategy": "Donchian20",
                    "status": "INSUFFICIENT_DATA",
                    "reasons": ["Only 20 closed trades; minimum is 30"],
                    "closed_trades": 20, "average_net_return": 0.026,
                    "profit_factor": 3.28, "positive_folds": 3,
                    "adequately_sampled_folds": 2, "folds": 4,
                    "double_cost_average_net_return": 0.019,
                    "eligible_for_shadow_scanner": False,
                },
            ],
        }
        compact = json.loads(_compact_report(report, registry=registry))
        self.assertEqual(len(compact["strategy_registry"]["strategies"]), 2)
        self.assertEqual(
            compact["strategy_registry"]["strategies"][0]["status"],
            "INSUFFICIENT_DATA",
        )
        self.assertFalse(
            compact["strategy_registry"]["strategies"][0]["eligible_for_shadow_scanner"]
        )
        cost_profile_code = compact["cost_model_by_ticker"]["GAZP"]
        cost_profile = compact["cost_model_profiles"][cost_profile_code]
        self.assertEqual(cost_profile["baseline_execution_config"]["fee_per_side"], 0.001)
        self.assertEqual(cost_profile["double_cost_execution_config"]["slippage_per_side"], 0.001)
        self.assertEqual(
            compact["strategy_registry"]["reason_codes"][
                compact["strategy_registry"]["strategies"][0]["reason_codes"][0]
            ],
            "Only 17 closed trades; minimum is 30",
        )
        self.assertIn("authoritative", compact["strategy_registry"]["authority_note"])

    def test_extract_text_requires_choice_text(self):
        self.assertEqual(
            _extract_text({"choices": [{"message": {"content": "OK"}}]}),
            "OK",
        )
        with self.assertRaises(RuntimeError):
            _extract_text({"choices": []})
        with self.assertRaises(RuntimeError):
            _extract_text({"choices": [{"message": {"content": ""}}]})

    def test_call_groq_uses_bearer_header_and_extracts_text(self):
        seen = {}

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["headers"] = dict(request.header_items())
            seen["body"] = json.loads(request.data)
            seen["timeout"] = timeout
            return FakeResponse({
                "choices": [{"message": {"role": "assistant", "content": "analysis"}}]
            })

        answer = call_groq("test prompt", api_key="secret-test", opener=opener)
        self.assertEqual(answer, "analysis")
        self.assertEqual(seen["url"], "https://api.groq.com/openai/v1/chat/completions")
        self.assertNotIn("secret-test", seen["url"])
        self.assertEqual(seen["headers"]["Authorization"], "Bearer secret-test")
        self.assertEqual(seen["timeout"], 60)
        self.assertEqual(seen["body"]["model"], DEFAULT_GROQ_MODEL)
        self.assertEqual(seen["body"]["messages"][0]["role"], "system")
        self.assertEqual(seen["body"]["max_completion_tokens"], 4096)


    def test_http_error_exposes_safe_provider_message_without_api_key(self):
        import io
        import urllib.error

        key = "secret-test-key"
        error_body = json.dumps({
            "error": {"message": "Invalid API Key", "type": "authentication_error"}
        }).encode("utf-8")

        def opener(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 403, "Forbidden", {}, io.BytesIO(error_body)
            )

        with self.assertRaisesRegex(RuntimeError, "HTTP 403: Invalid API Key") as caught:
            call_groq("test", api_key=key, opener=opener)
        self.assertNotIn(key, str(caught.exception))

    def test_run_team_calls_three_specialists_then_coordinator(self):
        calls = []

        def fake_caller(prompt, *, api_key, provider, model):
            calls.append((prompt, provider, model))
            return f"note-{len(calls)}"

        result = run_team(
            {"ticker": "SBER", "evidence": {"status": "UNKNOWN"}},
            api_key="not-a-real-key",
            caller=fake_caller,
        )
        self.assertEqual(len(calls), 4)
        self.assertEqual(result["calls"], 4)
        self.assertEqual(result["status"], "AI_COMMENTARY_ONLY")
        self.assertEqual(result["provider"], "openrouter")
        self.assertEqual(result["providers_used"], ["openrouter"] * 4)
        self.assertEqual(result["coordinator"], "note-4")
        self.assertEqual(result["model"], DEFAULT_MODEL)
        self.assertIn("no broker", " ".join(result["limitations"]).lower())

    def test_empty_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "GROQ_API_KEY"):
            call_groq("x", api_key=" ")

    def test_call_provider_uses_openrouter_endpoint_and_headers(self):
        seen = {}

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["headers"] = dict(request.header_items())
            seen["body"] = json.loads(request.data)
            return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

        answer = call_provider(
            "test", api_key="openrouter-secret", provider="openrouter",
            model="openrouter/free", opener=opener,
        )
        self.assertEqual(answer, "ok")
        self.assertEqual(seen["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer openrouter-secret")
        self.assertEqual(seen["body"]["model"], "openrouter/free")
        self.assertEqual(
            seen["body"]["reasoning"],
            {"effort": "low", "exclude": True},
        )

    def test_empty_openrouter_content_reports_finish_reason_and_reasoning_usage(self):
        payload = {
            "id": "gen-test-safe-id",
            "choices": [{
                "message": {"role": "assistant", "content": None},
                "finish_reason": "length",
                "native_finish_reason": "max_tokens",
            }],
            "usage": {
                "completion_tokens_details": {"reasoning_tokens": 1200}
            },
        }
        with self.assertRaisesRegex(
            RuntimeError,
            r"finish_reason=length.*reasoning_tokens=1200.*generation_id=gen-test-safe-id",
        ):
            _extract_text(payload, "openrouter")

    def test_openrouter_embedded_api_error_is_not_reported_as_empty_text(self):
        with self.assertRaisesRegex(
            RuntimeError, "openrouter returned API error 502: Provider unavailable"
        ):
            _extract_text(
                {"error": {"code": 502, "message": "Provider unavailable"}},
                "openrouter",
            )

    def test_openrouter_failure_uses_groq_fallback(self):
        calls = []

        def fake_caller(prompt, *, api_key, provider, model):
            calls.append(provider)
            if provider == "openrouter":
                raise RuntimeError("OpenRouter unavailable")
            return "fallback-note"

        result = run_team(
            {"ticker": "SBER"},
            api_key="openrouter-key",
            groq_api_key="groq-key",
            caller=fake_caller,
        )
        self.assertEqual(calls, ["openrouter", "groq"] * 4)
        self.assertEqual(result["providers_used"], ["groq_fallback"] * 4)
        self.assertEqual(result["coordinator"], "fallback-note")
        self.assertEqual(len(result["provider_diagnostics"]), 4)
        self.assertEqual(
            result["provider_diagnostics"][0]["primary_error"],
            "OpenRouter unavailable",
        )

    def test_both_provider_failures_are_preserved_in_error(self):
        def fake_caller(prompt, *, api_key, provider, model):
            if provider == "openrouter":
                raise RuntimeError("OpenRouter HTTP 429: rate limited")
            raise RuntimeError("Groq HTTP 403: model access denied")

        with self.assertRaisesRegex(
            RuntimeError,
            r"OpenRouter HTTP 429.*Groq HTTP 403",
        ):
            run_team(
                {"ticker": "SBER"},
                api_key="openrouter-key",
                groq_api_key="groq-key",
                caller=fake_caller,
            )


    def test_openrouter_model_fallback_uses_same_provider_and_records_diagnostics(self):
        calls = []

        def fake_caller(prompt, *, api_key, provider, model):
            calls.append((provider, model))
            if model == "primary-model":
                raise RuntimeError("primary model unavailable")
            return "backup-note"

        result = run_team(
            {"ticker": "SYNTHETIC_ONLY"},
            api_key="openrouter-key",
            model="primary-model",
            fallback_model="backup-model",
            caller=fake_caller,
        )
        self.assertEqual(len(calls), 8)
        self.assertEqual(calls[:2], [("openrouter", "primary-model"), ("openrouter", "backup-model")])
        self.assertEqual(result["providers_used"], ["openrouter_model_fallback"] * 4)
        self.assertEqual(result["coordinator"], "backup-note")
        self.assertEqual(result["provider_diagnostics"][0]["fallback_model"], "backup-model")
        self.assertEqual(result["provider_diagnostics"][0]["fallback_status"], "SUCCEEDED")


if __name__ == "__main__":
    unittest.main()
