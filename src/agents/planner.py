"""
Planner Agent — Phase 1 of the Agentic STLC.

Takes a raw requirement (plain English) and produces a structured TestPlan:
scope, out-of-scope, risk notes, and a set of TestCase scenarios with
priorities. This mirrors what a human QA lead does in a test-planning
meeting, and deliberately does NOT write executable steps yet — that's the
Test Generator's job (separation of "what to test" from "how to automate it"
keeps each prompt focused and each stage independently reviewable).

Prompt used here lives in prompt_library/01_planner_prompt.md — kept in its
own file so it can be versioned/evaluated independently of this code.
"""
from __future__ import annotations

import json
from pathlib import Path

from models.state import AgentState, TestPlan


PROMPT_PATH = Path(__file__).parent.parent.parent / "prompt_library" / "01_planner_prompt.md"


def load_planner_prompt() -> str:
    return PROMPT_PATH.read_text()


def build_planner_messages(requirement: str) -> list[dict]:
    system_prompt = load_planner_prompt()
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Requirement:\n{requirement}"},
    ]


def parse_plan_response(raw_response: str, requirement: str) -> TestPlan:
    cleaned = raw_response.strip().strip("`").removeprefix("json").strip()
    data = json.loads(cleaned)
    data["requirement"] = requirement
    return TestPlan(**data)


async def plan_node(state: AgentState, llm_client) -> dict:
    """
    LangGraph node. `llm_client` is injected (see graph.py) so this function
    stays unit-testable with a fake/stub client — no network calls in tests.
    """
    requirement = state["requirement"]
    messages = build_planner_messages(requirement)

    raw_response = await llm_client.complete(messages)
    test_plan = parse_plan_response(raw_response, requirement)

    return {
        "test_plan": test_plan,
        "generation_attempts": 0,
        "guardrail_retry_count": 0,
        "healing_attempts": 0,
    }
