"""
Self-Healing Agent — Phase 4b of the Agentic STLC (triggered on locator/timeout
failures from the Executor).

The #1 cause of flaky UI test suites in real orgs is locator drift: a
developer renames a button's id/class/data-testid and every hard-coded
selector referencing it silently breaks. This agent:

  1. Pulls the CURRENT DOM via `get_page_source` (MCP call).
  2. Asks the LLM to propose a replacement locator for the failed step by
     diffing what the test expected against what's actually on the page.
  3. Patches the specific TestCase.step in place and hands control back to
     the Executor for a retry (bounded to 2 attempts total — see
     route_after_execution in executor.py).

If the LLM can't find a confident replacement (e.g. the element is genuinely
gone — a real regression, not a rename), it returns None and the graph routes
to the Reporter as a real defect, not an infinite healing loop.
"""
from __future__ import annotations

import json

from models.state import AgentState, TestCase


PROMPT_PATH_TEXT = """You are a self-healing test locator agent. A Selenium
test step failed because its locator no longer matches any element on the
page. You are given the ORIGINAL locator, the step's intent, and the CURRENT
page HTML. Propose a replacement locator strategy and value that most likely
targets the same logical element (e.g. the same button, now with a different
id/class/data-testid).

Rules:
- Prefer stable attributes: data-testid > id > name > css class > text content.
- If you cannot identify a confident match, return {"confident": false}.
- Respond ONLY with JSON: {"confident": bool, "by": string, "value": string, "reasoning": string}
"""


def build_heal_prompt(failure, dom_html: str, original_step) -> list[dict]:
    user_content = (
        f"Original locator: by='{failure.original_locator and original_step.by}', "
        f"value='{failure.original_locator}'\n"
        f"Step intent (action): {original_step.action}\n"
        f"Current page HTML:\n{dom_html}\n\n"
        "Propose a replacement locator."
    )
    return [
        {"role": "system", "content": PROMPT_PATH_TEXT},
        {"role": "user", "content": user_content},
    ]


def parse_heal_response(raw_response: str) -> dict | None:
    cleaned = raw_response.strip().strip("`").removeprefix("json").strip()
    data = json.loads(cleaned)
    if not data.get("confident"):
        return None
    return {"by": data["by"], "value": data["value"], "reasoning": data.get("reasoning", "")}


def patch_test_case(test_case: TestCase, step_index: int, by: str, value: str) -> TestCase:
    patched_steps = list(test_case.steps)
    old_step = patched_steps[step_index]
    patched_steps[step_index] = old_step.model_copy(update={"by": by, "value": value})
    return test_case.model_copy(update={"steps": patched_steps})


async def heal_node(state: AgentState, llm_client, mcp_client) -> dict:
    failures = state.get("failures", [])
    tests_by_id = {t.id: t for t in state["generated_tests"]}
    healed_tests = dict(tests_by_id)
    unhealed_failures = []

    for failure in failures:
        if failure.reason not in ("locator_not_found", "timeout"):
            continue

        test_case = tests_by_id[failure.test_id]
        original_step = test_case.steps[failure.step_index]

        dom_result = await mcp_client.call("get_page_source")
        dom_html = dom_result.get("html", "") if isinstance(dom_result, dict) else str(dom_result)

        messages = build_heal_prompt(failure, dom_html, original_step)
        raw_response = await llm_client.complete(messages)
        proposal = parse_heal_response(raw_response)

        if proposal is None:
            unhealed_failures.append(failure)
            continue

        healed_tests[test_case.id] = patch_test_case(
            test_case, failure.step_index, proposal["by"], proposal["value"]
        )

    return {
        "generated_tests": list(healed_tests.values()),
        "healing_attempts": state.get("healing_attempts", 0) + 1,
        "failures": unhealed_failures,
    }
