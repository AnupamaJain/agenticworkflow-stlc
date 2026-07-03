"""
Guardrail Agent — Phase 3 of the Agentic STLC.

Reviews EVERY generated test case before any of them are allowed to reach the
Execution Agent / real browser. Two layers, cheapest first:

  1. Deterministic quick-reject (no LLM call) — guardrails/llm_guardrail_reviewer.quick_reject_reasons
  2. LLM review for anything that passes the quick check — catches scope creep,
     missing assertions in context, logical ordering issues.

A single violation on ANY test case in the batch fails the whole batch back to
the Generator (state.guardrail_verdict.approved = False) — we don't execute a
partially-approved batch, to keep the retry loop simple and auditable.
"""
from __future__ import annotations

from guardrails.llm_guardrail_reviewer import (
    build_review_prompt,
    parse_guardrail_response,
    quick_reject_reasons,
)
from models.state import AgentState, GuardrailVerdict


MAX_GUARDRAIL_RETRIES = 3


async def guardrail_node(state: AgentState, llm_client) -> dict:
    tests = state["generated_tests"]
    requirement = state["requirement"]
    all_violations: list[str] = []
    reasonings: list[str] = []

    for test in tests:
        quick_reasons = quick_reject_reasons(test)
        if quick_reasons:
            all_violations.extend(f"[{test.id}] {r}" for r in quick_reasons)
            continue  # skip LLM call, already rejected deterministically

        prompt = build_review_prompt(requirement, test)
        raw_response = await llm_client.complete([
            {"role": "system", "content": "You are the guardrail reviewer."},
            {"role": "user", "content": prompt},
        ])
        verdict = parse_guardrail_response(raw_response)
        if not verdict.approved:
            all_violations.extend(f"[{test.id}] {v}" for v in verdict.violations)
        reasonings.append(f"[{test.id}] {verdict.reasoning}")

    final_verdict = GuardrailVerdict(
        approved=len(all_violations) == 0,
        violations=all_violations,
        reasoning=" | ".join(reasonings),
    )

    return {
        "guardrail_verdict": final_verdict,
        "guardrail_retry_count": state.get("guardrail_retry_count", 0) + (0 if final_verdict.approved else 1),
    }


def route_after_guardrail(state: AgentState) -> str:
    """Conditional edge used by graph.py."""
    verdict = state.get("guardrail_verdict")
    retry_count = state.get("guardrail_retry_count", 0)

    if verdict and not verdict.approved:
        if retry_count >= MAX_GUARDRAIL_RETRIES:
            return "report"  # give up regenerating, report as a tooling failure
        return "generate"

    if state.get("target_env") != "sandbox":
        return "human_approval"

    return "execute"
