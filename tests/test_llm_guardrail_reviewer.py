"""
Unit tests for guardrails/llm_guardrail_reviewer.py — the parsing/quick-reject
logic (not the LLM call itself, which is exercised via evaluation/ instead).
Run: pytest tests/test_llm_guardrail_reviewer.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from guardrails.llm_guardrail_reviewer import (
    has_at_least_one_assertion,
    parse_guardrail_response,
    quick_reject_reasons,
)
from models.state import TestCase, TestStep


def make_test_case(steps):
    return TestCase(id="TC-001", title="t", priority="P0", steps=steps)


def test_has_assertion_true():
    tc = make_test_case([TestStep(action="get_text", expected="foo")])
    assert has_at_least_one_assertion(tc) is True


def test_has_assertion_false():
    tc = make_test_case([TestStep(action="click", by="css", value="#btn")])
    assert has_at_least_one_assertion(tc) is False


def test_quick_reject_flags_no_assertion():
    tc = make_test_case([TestStep(action="click", by="css", value="#btn")])
    reasons = quick_reject_reasons(tc)
    assert any("No assertion" in r for r in reasons)


def test_quick_reject_flags_destructive_term():
    tc = make_test_case([
        TestStep(action="click", by="css", value="#delete-account-btn"),
        TestStep(action="get_text", expected="ok"),
    ])
    reasons = quick_reject_reasons(tc)
    assert any("suspicious" in r.lower() for r in reasons)


def test_quick_reject_clean_test_case():
    tc = make_test_case([TestStep(action="get_text", by="css", value=".banner", expected="Invalid")])
    assert quick_reject_reasons(tc) == []


def test_parse_valid_guardrail_response():
    raw = '{"approved": true, "violations": [], "reasoning": "looks fine"}'
    verdict = parse_guardrail_response(raw)
    assert verdict.approved is True
    assert verdict.violations == []


def test_parse_response_with_markdown_fences():
    raw = '```json\n{"approved": false, "violations": ["scope creep"], "reasoning": "bad"}\n```'
    verdict = parse_guardrail_response(raw)
    assert verdict.approved is False
    assert verdict.violations == ["scope creep"]


def test_parse_malformed_response_fails_closed():
    raw = "not valid json at all"
    verdict = parse_guardrail_response(raw)
    assert verdict.approved is False
    assert "guardrail_parse_error" in verdict.violations
