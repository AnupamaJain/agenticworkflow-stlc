"""
Execution Agent — Phase 4 of the Agentic STLC.

Runs each approved TestCase step-by-step via MCPToolClient against a real (or
mocked, in demo mode) browser session through the Selenium MCP server. This
node contains NO LLM calls — it is deterministic execution + result capture.
The only "intelligence" here is failure classification (locator vs timeout vs
real assertion failure), which decides whether to route to the Self-Healing
Agent or straight to the Reporter.
"""
from __future__ import annotations

import time

from guardrails.mcp_guardrails import GuardrailViolation
from models.state import AgentState, TestFailure, TestResult
from tools.mcp_client import MCPToolClient


LOCATOR_ERROR_MARKERS = ("NoSuchElementException", "ElementNotFoundError", "not found")
TIMEOUT_ERROR_MARKERS = ("TimeoutException", "timed out")


def classify_failure(error_message: str) -> str:
    if any(m.lower() in error_message.lower() for m in LOCATOR_ERROR_MARKERS):
        return "locator_not_found"
    if any(m.lower() in error_message.lower() for m in TIMEOUT_ERROR_MARKERS):
        return "timeout"
    return "assertion_failed"


async def run_single_test(test_case, mcp_client: MCPToolClient) -> tuple[TestResult, TestFailure | None]:
    start = time.time()
    steps_executed = 0

    for i, step in enumerate(test_case.steps):
        try:
            call_kwargs = {k: v for k, v in {
                "url": step.value if step.action == "navigate" else None,
                "by": step.by,
                "value": step.value,
                "input_text": step.input_text,
            }.items() if v is not None}

            result = await mcp_client.call(step.action, **call_kwargs)
            steps_executed += 1

            if step.expected is not None:
                actual = result.get("text", "") if isinstance(result, dict) else str(result)
                if step.expected.strip().lower() not in actual.strip().lower():
                    duration_ms = int((time.time() - start) * 1000)
                    return (
                        TestResult(
                            test_id=test_case.id, status="failed", duration_ms=duration_ms,
                            steps_executed=steps_executed, failure_reason="assertion_failed",
                            error_message=f"Expected '{step.expected}' in actual '{actual}'",
                        ),
                        None,
                    )

        except GuardrailViolation as e:
            duration_ms = int((time.time() - start) * 1000)
            return (
                TestResult(
                    test_id=test_case.id, status="error", duration_ms=duration_ms,
                    steps_executed=steps_executed, failure_reason="unknown",
                    error_message=f"Guardrail blocked execution: {e}",
                ),
                None,
            )
        except Exception as e:  # noqa: BLE001
            duration_ms = int((time.time() - start) * 1000)
            reason = classify_failure(str(e))
            failure = TestFailure(
                test_id=test_case.id, step_index=i, reason=reason,
                original_locator=step.value,
            )
            return (
                TestResult(
                    test_id=test_case.id, status="failed", duration_ms=duration_ms,
                    steps_executed=steps_executed, failure_reason=reason,
                    error_message=str(e),
                ),
                failure,
            )

    duration_ms = int((time.time() - start) * 1000)
    return (
        TestResult(
            test_id=test_case.id, status="passed", duration_ms=duration_ms,
            steps_executed=steps_executed,
        ),
        None,
    )


async def execute_node(state: AgentState, mcp_client: MCPToolClient) -> dict:
    tests = state["generated_tests"]
    results: list[TestResult] = []
    failures: list[TestFailure] = []

    for test_case in tests:
        result, failure = await run_single_test(test_case, mcp_client)
        results.append(result)
        if failure:
            failures.append(failure)

    return {"execution_results": results, "failures": failures}


def route_after_execution(state: AgentState) -> str:
    """Conditional edge used by graph.py."""
    failures = state.get("failures", [])
    healing_attempts = state.get("healing_attempts", 0)

    healable = [f for f in failures if f.reason in ("locator_not_found", "timeout")]
    if healable and healing_attempts < 2:
        return "heal"
    return "report"
