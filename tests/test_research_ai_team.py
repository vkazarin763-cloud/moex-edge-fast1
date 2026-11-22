"""Offline tests for the optional Groq research team."""
import json
import unittest

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
    def test_compact_report_rejects_oversized_raw_data(self):
        with self.assertRaisesRegex(ValueError, "compact validated summary"):
            _compact_report({"raw": "x" * MAX_INPUT_CHARS})

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
        self.assertEqual(seen["body"]["model"], DEFAULT_MODEL)
        self.assertEqual(seen["body"]["messages"][0]["role"], "system")
        self.assertEqual(seen["body"]["max_completion_tokens"], 1200)

    def test_run_team_calls_three_specialists_then_coordinator(self):
        calls = []

        def fake_caller(prompt, *, api_key, model):
            calls.append((prompt, model))
            return f"note-{len(calls)}"

        result = run_team(
            {"ticker": "SBER", "evidence": {"status": "UNKNOWN"}},
            api_key="not-a-real-key",
            caller=fake_caller,
        )
        self.assertEqual(len(calls), 4)
        self.assertEqual(result["calls"], 4)
        self.assertEqual(result["status"], "AI_COMMENTARY_ONLY")
        self.assertEqual(result["provider"], "groq_api")
        self.assertEqual(result["coordinator"], "note-4")
        self.assertEqual(result["model"], DEFAULT_MODEL)
        self.assertIn("no broker", " ".join(result["limitations"]).lower())

    def test_empty_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "GROQ_API_KEY"):
            call_groq("x", api_key=" ")


if __name__ == "__main__":
    unittest.main()
