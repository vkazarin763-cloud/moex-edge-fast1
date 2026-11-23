"""Offline tests for the optional Groq research team."""
import json
import unittest

from research_agent.evidence_guard import EVIDENCE_RESPONSE_FORMAT, validate_commentary
from research_agent.ai_team import (
    DEFAULT_MODEL,
    MAX_INPUT_CHARS,
    _compact_report,
    _extract_text,
    call_groq,
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

    def test_extract_text_requires_choice_text(self):
        self.assertEqual(
            _extract_text({"choices": [{"message": {"content": "OK"}}]}),
            "OK",
        )
        with self.assertRaises(RuntimeError):
            _extract_text({"choices": []})
        with self.assertRaisesRegex(RuntimeError, "finish_reason=length") as caught:
            _extract_text({
                "choices": [{
                    "finish_reason": "length",
                    "message": {"content": "", "reasoning": "private reasoning"},
                }],
                "usage": {"completion_tokens": 1200, "prompt_tokens": 800},
            })
        self.assertIn("reasoning_present=True", str(caught.exception))
        self.assertNotIn("private reasoning", str(caught.exception))

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
        self.assertEqual(
            seen["headers"]["User-agent"],
            "MOEX-EDGE-Research/1.0 (+https://github.com/vkazarin763-cloud/moex-edge-fast1)",
        )
        self.assertEqual(seen["timeout"], 60)
        self.assertEqual(seen["body"]["model"], DEFAULT_MODEL)
        self.assertEqual(seen["body"]["messages"][0]["role"], "system")
        self.assertEqual(seen["body"]["max_completion_tokens"], 700)
        self.assertIs(seen["body"]["include_reasoning"], False)
        self.assertEqual(seen["body"]["reasoning_effort"], "low")
        self.assertEqual(seen["body"]["response_format"], EVIDENCE_RESPONSE_FORMAT)


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


    def test_http_429_waits_for_provider_retry_hint_then_succeeds(self):
        import io
        import urllib.error

        attempts = []
        waits = []

        def opener(request, timeout):
            attempts.append(1)
            if len(attempts) == 1:
                body = json.dumps({
                    "error": {"message": "Rate limit reached. Please try again in 17.34s."}
                }).encode("utf-8")
                raise urllib.error.HTTPError(
                    request.full_url, 429, "Too Many Requests", {}, io.BytesIO(body)
                )
            return FakeResponse({
                "choices": [{"message": {"content": "recovered"}}]
            })

        answer = call_groq(
            "test",
            api_key="secret-test",
            opener=opener,
            sleeper=waits.append,
        )
        self.assertEqual(answer, "recovered")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(waits, [18.09])

    def test_run_team_calls_three_specialists_then_coordinator(self):
        calls = []

        def fake_caller(prompt, *, api_key, model):
            calls.append((prompt, model))
            return json.dumps({
                "hypotheses": [{
                    "hypothesis": "A qualitative possibility worth checking",
                    "evidence": [{"path": "evidence.status", "value_json": '"UNKNOWN"'}],
                }],
                "questions": ["What additional evidence is needed?"],
            })

        result = run_team(
            {"ticker": "SBER", "evidence": {"status": "UNKNOWN"}},
            api_key="not-a-real-key",
            caller=fake_caller,
        )
        self.assertEqual(len(calls), 4)
        self.assertEqual(result["calls"], 4)
        self.assertEqual(result["status"], "AI_COMMENTARY_EVIDENCE_CHECKED")
        self.assertEqual(result["provider"], "groq_api")
        self.assertEqual(result["coordinator"]["status"], "EVIDENCE_REFERENCES_VALIDATED")
        self.assertEqual(result["fact_check"]["status"], "PASS")
        self.assertEqual(result["fact_check"]["validated_evidence_references"], 4)
        self.assertEqual(result["model"], DEFAULT_MODEL)
        self.assertIn("no broker", " ".join(result["limitations"]).lower())


    def test_evidence_guard_accepts_exact_source_value(self):
        source = {"cross_sectional": {"SHORT": {"trades": 79}}}
        response = json.dumps({
            "hypotheses": [{
                "hypothesis": "A possible difference between the two directions deserves review",
                "evidence": [{
                    "path": "cross_sectional.SHORT.trades",
                    "value_json": "79",
                }],
            }],
            "questions": ["Could the underlying trades be inspected?"],
        })
        checked = validate_commentary(response, source)
        self.assertEqual(checked["status"], "EVIDENCE_REFERENCES_VALIDATED")
        self.assertEqual(checked["evidence_reference_count"], 1)
        self.assertEqual(checked["hypotheses"][0]["evidence"][0]["value"], 79)

    def test_evidence_guard_rejects_fabricated_or_mismatched_value(self):
        source = {"audit": {"walk_forward_folds_checked": 20}}
        response = json.dumps({
            "hypotheses": [{
                "hypothesis": "The sample structure deserves review",
                "evidence": [{
                    "path": "audit.walk_forward_folds_checked",
                    "value_json": "20 per ticker",
                }],
            }],
            "questions": [],
        })
        with self.assertRaisesRegex(ValueError, "value mismatch"):
            validate_commentary(response, source)

    def test_evidence_guard_rejects_numeric_claims_in_free_text(self):
        source = {"audit": {"walk_forward_folds_checked": 20}}
        response = json.dumps({
            "hypotheses": [{
                "hypothesis": "There are 20 folds per ticker",
                "evidence": [{
                    "path": "audit.walk_forward_folds_checked",
                    "value_json": "20",
                }],
            }],
            "questions": [],
        })
        with self.assertRaisesRegex(ValueError, "Numeric claims"):
            validate_commentary(response, source)

    def test_evidence_guard_rejects_missing_evidence_and_bad_json(self):
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            validate_commentary("not json", {})
        response = json.dumps({
            "hypotheses": [{"hypothesis": "An unsupported assertion", "evidence": []}],
            "questions": [],
        })
        with self.assertRaisesRegex(ValueError, "at least one"):
            validate_commentary(response, {})

    def test_empty_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "GROQ_API_KEY"):
            call_groq("x", api_key=" ")


if __name__ == "__main__":
    unittest.main()
