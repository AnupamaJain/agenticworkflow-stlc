"""
Test Generator Agent — Phase 2 of the Agentic STLC.

Takes the structured TestPlan from the Planner and generates executable
TestCase.steps — the actual sequence of MCP tool calls (navigate, find_element,
send_keys, click, get_text with an `expected` assertion) needed to automate
each scenario in a real browser.

If the Guardrail agent rejects a generated test, this node is re-entered with
`guardrail_verdict.violations` appended to the prompt as corrective feedback
(see graph.py's conditional edge `route_after_guardrail`), which is why this
node reads `state.get("guardrail_verdict")` — it's the retry path.
"""
from __future__ import annotations

import json
from pathlib import Path

from models.state import AgentState, TestCase


PROMPT_PATH = Path(__file__).parent.parent.parent / "prompt_library" / "02_test_generator_prompt.md"
TOOL_SCHEMA_PATH = Path(__file__).parent.parent.parent / "prompt_library" / "tool_schemas.json"


def load_generator_prompt() -> str:
    return PROMPT_PATH.read_text()


def load_tool_schemas() -> str:
    return TOOL_SCHEMA_PATH.read_text()


def build_generator_messages(state: AgentState) -> list[dict]:
    system_prompt = load_generator_prompt()
    tool_schemas = load_tool_schemas()
    test_plan = state["test_plan"]

    user_content = (
        f"Test plan scenarios (write executable steps for ALL of these):\n"
        f"{json.dumps([s.model_dump() for s in test_plan.scenarios], indent=2)}\n\n"
        f"Available MCP tools (use ONLY these action names):\n{tool_schemas}"
    )

    verdict = state.get("guardrail_verdict")
    if verdict is not None and not verdict.approved:
        user_content += (
            f"\n\nYour previous attempt was REJECTED by the guardrail reviewer for:\n"
            f"{json.dumps(verdict.violations, indent=2)}\n"
            f"Reasoning: {verdict.reasoning}\n"
            "Fix these issues in your next attempt."
        )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def parse_generated_tests(raw_response: str) -> list[TestCase]:
    cleaned = raw_response.strip().strip("`").removeprefix("json").strip()
    data = json.loads(cleaned)
    return [TestCase(**tc) for tc in data["test_cases"]]


async def generate_node(state: AgentState, llm_client) -> dict:
    messages = build_generator_messages(state)
    raw_response = await llm_client.complete(messages)
    generated_tests = parse_generated_tests(raw_response)

    return {
        "generated_tests": generated_tests,
        "generation_attempts": state.get("generation_attempts", 0) + 1,
    }
