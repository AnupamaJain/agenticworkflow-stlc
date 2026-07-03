"""
FakeLLMClient — a scripted, deterministic stand-in for a real LLM client, used
so `python langgraph_agent/graph.py` runs end-to-end with zero API keys and
zero network calls, for demos, interviews, and CI.

It pattern-matches on the system prompt content to decide which canned
response to return — this is NOT a mock of behavior we're hiding, it's the
literal set of responses a real model gives for THIS exact demo requirement,
captured once so the repo is runnable offline. See src/tools/real_llm_client.py
for the drop-in replacement that calls the real Anthropic API — swapping one
for the other requires no changes to any agent code (same `.complete()`
interface), which is the point.
"""
from __future__ import annotations

import json


LOGIN_TEST_PLAN_RESPONSE = json.dumps({
    "scope": "Verify login form correctly rejects invalid credentials and displays "
             "the appropriate error message on the demo login page.",
    "out_of_scope": ["Password reset flow", "Account lockout after N attempts", "SSO login"],
    "risk_notes": [
        "Error message text is an exact-match assertion; a future copy change would need this test updated.",
    ],
    "scenarios": [
        {
            "id": "TC-001",
            "title": "Login fails with correct username and incorrect password",
            "priority": "P0",
            "preconditions": ["User navigates to the login page", "A valid username exists in the system"],
            "steps": [],
            "tags": ["auth", "negative", "smoke"],
        }
    ],
}, indent=2)


LOGIN_GENERATED_TESTS_RESPONSE = json.dumps({
    "test_cases": [
        {
            "id": "TC-001",
            "title": "Login fails with correct username and incorrect password",
            "priority": "P0",
            "preconditions": ["User navigates to the login page"],
            "tags": ["auth", "negative", "smoke"],
            "steps": [
                {"action": "navigate", "by": None, "value": "https://demo.aiqef.local/login", "input_text": None, "expected": None},
                {"action": "send_keys", "by": "id", "value": "username", "input_text": "demo_user", "expected": None},
                {"action": "send_keys", "by": "id", "value": "password", "input_text": "wrong-password-123", "expected": None},
                {"action": "click", "by": "css", "value": "#submit-btn-old", "input_text": None, "expected": None},
                {"action": "get_text", "by": "css", "value": ".error-banner", "input_text": None, "expected": "Invalid username or password"},
            ],
        }
    ]
})


GUARDRAIL_APPROVED_RESPONSE = json.dumps({
    "approved": True,
    "violations": [],
    "reasoning": "Test stays within the stated requirement (negative login check), "
                 "uses obviously-fake credentials, and contains a real assertion "
                 "on the error banner text. No scope creep or destructive actions detected.",
})


HEAL_RESPONSE = json.dumps({
    "confident": True,
    "by": "css",
    "value": "button[data-testid='submit']",
    "reasoning": "The current DOM has no element matching '#submit-btn-old', but contains "
                 "a <button data-testid='submit'> with text 'Sign In' in the same form "
                 "position — this is almost certainly the renamed submit button.",
})


BUG_REPORT_RESPONSE = """## Test Run Summary

**Status:** ✅ 1/1 passed (1 self-healed)

### TC-001 — Login fails with correct username and incorrect password
- **Result:** PASSED (after self-healing)
- **Note:** The submit button locator `#submit-btn-old` no longer matched any
  element on the page (likely renamed during a recent frontend change). The
  Self-Healing Agent inspected the live DOM, identified
  `button[data-testid='submit']` as the current equivalent, patched the test,
  and the retry passed with the expected error message
  `"Invalid username or password"` correctly displayed.
- **Suggested action:** No bug filed — this was a test-maintenance issue, not
  an application defect. Recommend updating the source-of-truth locator in
  the test repo to `button[data-testid='submit']` so future runs don't need
  to re-heal this every time.
- **Severity:** N/A (no product defect found)
"""


class FakeLLMClient:
    """Scripted client — routes on system prompt keywords to canned JSON responses."""

    def __init__(self):
        self.call_count = 0
        self.call_log: list[dict] = []

    async def complete(self, messages: list[dict]) -> str:
        self.call_count += 1
        system = messages[0]["content"] if messages else ""
        self.call_log.append({"call_index": self.call_count, "system_excerpt": system[:80]})

        if "test-planning" in system.lower() or "planner" in system.lower():
            return LOGIN_TEST_PLAN_RESPONSE
        if "test generator" in system.lower() or "executable steps" in system.lower():
            return LOGIN_GENERATED_TESTS_RESPONSE
        if "guardrail reviewer" in system.lower():
            return GUARDRAIL_APPROVED_RESPONSE
        if "self-healing" in system.lower() or "locator agent" in system.lower():
            return HEAL_RESPONSE
        if "bug report" in system.lower():
            return BUG_REPORT_RESPONSE

        raise ValueError(f"FakeLLMClient has no scripted response for system prompt: {system[:100]}")
