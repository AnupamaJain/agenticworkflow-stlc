"""
LLM-based guardrail review — runs ONCE per generated test case (not per tool
call, unlike guardrails/mcp_guardrails.py which is deterministic and runs on
every single MCP call).

Purpose: catch things a regex/allow-list can't — scope creep ("this test also
deletes the admin account, which was never asked for"), missing assertions,
tests that would only pass vacuously, or steps that don't match the actual
requirement's intent.

This is the guardrail_node in the LangGraph (src/agents/guardrail.py imports
`review_test_case` from here).
"""
from __future__ import annotations

import json

from models.state import GuardrailVerdict, TestCase


GUARDRAIL_SYSTEM_PROMPT = """You are a strict QA guardrail reviewer. You review a
single AI-generated test case before it is allowed to execute against a real
browser session.

Reject the test if ANY of the following are true:
1. It performs an action not implied by the original requirement (scope creep) —
   e.g. deleting data, changing account settings, navigating off the target
   domain, when the requirement only asked to verify a login error message.
2. It has no real assertion (an `expected` value) on at least one step — a test
   that only clicks around without checking anything is not a valid test.
3. It uses locators that look destructive-by-name (e.g. targeting a
   'delete-account' or 'admin-panel' button) that are irrelevant to the stated
   requirement.
4. It hardcodes what looks like a real secret (real-looking card numbers, SSNs,
   API keys) rather than obviously-fake fixture data.
5. Steps are logically out of order (e.g. asserting an error message before
   submitting the form).

Respond ONLY with JSON matching this schema, no prose outside the JSON:
{
  "approved": bool,
  "violations": [string],   // empty list if approved
  "reasoning": string       // 1-3 sentences
}
"""


def build_review_prompt(requirement: str, test_case: TestCase) -> str:
    return (
        f"Original requirement:\n{requirement}\n\n"
        f"Generated test case (JSON):\n{test_case.model_dump_json(indent=2)}\n\n"
        "Review this test case per your instructions and respond with the JSON verdict."
    )


def parse_guardrail_response(raw_response: str) -> GuardrailVerdict:
    """
    Parses the LLM's JSON verdict. Fails closed: if the response can't be
    parsed as valid JSON matching the schema, the test is rejected rather
    than silently approved — a guardrail that fails open is not a guardrail.
    """
    try:
        cleaned = raw_response.strip().strip("`").removeprefix("json").strip()
        data = json.loads(cleaned)
        return GuardrailVerdict(**data)
    except Exception as e:  # noqa: BLE001
        return GuardrailVerdict(
            approved=False,
            violations=["guardrail_parse_error"],
            reasoning=f"Could not parse guardrail LLM response as valid verdict JSON: {e}. "
                      "Failing closed (rejecting) rather than risking a false approval.",
        )


# --- Deterministic pre-checks that run BEFORE spending an LLM call ------------
# Cheap, catches the obvious cases so we don't burn tokens on every review.

def has_at_least_one_assertion(test_case: TestCase) -> bool:
    return any(step.expected is not None for step in test_case.steps)


def quick_reject_reasons(test_case: TestCase) -> list[str]:
    reasons = []
    if not has_at_least_one_assertion(test_case):
        reasons.append("No assertion step (expected value) found in test case.")
    suspicious_terms = ["delete", "drop", "admin", "wipe", "purge"]
    for step in test_case.steps:
        haystack = f"{step.value or ''} {step.action}".lower()
        if any(term in haystack for term in suspicious_terms):
            reasons.append(f"Step references suspicious/destructive term: '{step.value}'")
    return reasons
