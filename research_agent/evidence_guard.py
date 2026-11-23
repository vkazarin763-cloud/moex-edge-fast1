"""Evidence-reference validation for Groq's hypothesis-only research commentary."""
from __future__ import annotations

import json
import re
from typing import Any

EVIDENCE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "moex_evidence_backed_hypotheses",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "hypotheses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "hypothesis": {"type": "string"},
                            "evidence": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "path": {"type": "string"},
                                        "value_json": {"type": "string"},
                                    },
                                    "required": ["path", "value_json"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["hypothesis", "evidence"],
                        "additionalProperties": False,
                    },
                },
                "questions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["hypotheses", "questions"],
            "additionalProperties": False,
        },
    },
}


def _resolve_path(source: Any, path: str) -> Any:
    """Resolve a dot-separated path through dictionaries only."""
    if not isinstance(path, str) or not path or any(not part for part in path.split(".")):
        raise ValueError("Evidence path is empty or malformed.")
    current = source
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ValueError(f"Evidence path does not exist: {path}")
    if isinstance(current, (dict, list)):
        raise ValueError(f"Evidence path must identify a scalar value: {path}")
    return current


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_commentary(raw_text: str, source_report: dict[str, Any]) -> dict[str, Any]:
    """Accept only hypothesis/question JSON whose evidence values exactly match source."""
    try:
        payload = json.loads(raw_text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Agent response is not valid JSON; commentary rejected.") from exc

    if not isinstance(payload, dict) or set(payload) != {"hypotheses", "questions"}:
        raise ValueError("Agent response has an unexpected top-level structure.")
    hypotheses = payload["hypotheses"]
    questions = payload["questions"]
    if not isinstance(hypotheses, list) or not isinstance(questions, list):
        raise ValueError("Hypotheses and questions must be arrays.")

    accepted_hypotheses = []
    evidence_count = 0
    for item in hypotheses:
        if not isinstance(item, dict) or set(item) != {"hypothesis", "evidence"}:
            raise ValueError("A hypothesis has an unexpected structure.")
        statement = item["hypothesis"]
        refs = item["evidence"]
        if not isinstance(statement, str) or not statement.strip() or len(statement) > 700:
            raise ValueError("A hypothesis must be a non-empty string of at most 700 characters.")
        if re.search(r"\d", statement):
            raise ValueError("Numeric claims are not allowed in free-text hypotheses.")
        if not isinstance(refs, list) or not refs:
            raise ValueError("Every hypothesis must cite at least one source-report field.")

        accepted_refs = []
        seen_paths = set()
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {"path", "value_json"}:
                raise ValueError("An evidence reference has an unexpected structure.")
            path = ref["path"]
            value_json = ref["value_json"]
            if not isinstance(path, str) or not isinstance(value_json, str):
                raise ValueError("Evidence path and value_json must be strings.")
            if path in seen_paths:
                raise ValueError("Duplicate evidence path in one hypothesis.")
            seen_paths.add(path)
            actual = _resolve_path(source_report, path)
            if value_json != _canonical_json(actual):
                raise ValueError(f"Evidence value mismatch for source path: {path}")
            accepted_refs.append({"path": path, "value": actual})
            evidence_count += 1

        accepted_hypotheses.append({
            "hypothesis": statement.strip(),
            "evidence": accepted_refs,
            "classification": "UNVERIFIED_HYPOTHESIS",
        })

    accepted_questions = []
    for question in questions:
        if not isinstance(question, str) or not question.strip() or len(question) > 500:
            raise ValueError("Each research question must be a non-empty string of at most 500 characters.")
        if re.search(r"\d", question):
            raise ValueError("Numeric claims are not allowed in free-text questions.")
        accepted_questions.append(question.strip())

    return {
        "status": "EVIDENCE_REFERENCES_VALIDATED",
        "hypotheses": accepted_hypotheses,
        "questions": accepted_questions,
        "evidence_reference_count": evidence_count,
    }
