"""
Typed state schema shared across every LangGraph node.

This is the single source of truth threaded through the graph. Every agent
reads what it needs from AgentState and returns a partial update (LangGraph
merges partial dict returns into state), so nodes stay side-effect-transparent
and easy to unit test in isolation.
"""
from __future__ import annotations

from typing import Literal, TypedDict
from pydantic import BaseModel, Field


TargetEnv = Literal["sandbox", "staging", "production"]
FailureReason = Literal["locator_not_found", "timeout", "assertion_failed", "unknown"]


class TestStep(BaseModel):
    """A single MCP tool call that makes up one line of a test case."""
    action: str = Field(..., description="MCP tool name, e.g. 'click', 'navigate'")
    by: str | None = Field(None, description="Locator strategy: css, xpath, id, text")
    value: str | None = Field(None, description="Locator value")
    input_text: str | None = Field(None, description="Text to type, if action=send_keys")
    expected: str | None = Field(None, description="Expected result for assertion steps")


class TestCase(BaseModel):
    id: str
    title: str
    priority: Literal["P0", "P1", "P2"]
    preconditions: list[str] = Field(default_factory=list)
    steps: list[TestStep]
    tags: list[str] = Field(default_factory=list)


class TestPlan(BaseModel):
    requirement: str
    scope: str
    out_of_scope: list[str] = Field(default_factory=list)
    scenarios: list[TestCase]
    risk_notes: list[str] = Field(default_factory=list)


class GuardrailVerdict(BaseModel):
    approved: bool
    violations: list[str] = Field(default_factory=list)
    reasoning: str


class TestResult(BaseModel):
    test_id: str
    status: Literal["passed", "failed", "healed_passed", "error"]
    duration_ms: int
    steps_executed: int
    failure_reason: FailureReason | None = None
    error_message: str | None = None
    screenshot_path: str | None = None


class TestFailure(BaseModel):
    test_id: str
    step_index: int
    reason: FailureReason
    original_locator: str | None
    dom_snapshot_excerpt: str | None = None


class AgentState(TypedDict, total=False):
    # input
    requirement: str
    target_env: TargetEnv
    trace_id: str

    # planning
    test_plan: TestPlan | None

    # generation
    generated_tests: list[TestCase]
    generation_attempts: int

    # guardrail
    guardrail_verdict: GuardrailVerdict | None
    guardrail_retry_count: int

    # execution
    execution_results: list[TestResult]
    failures: list[TestFailure]
    healing_attempts: int

    # reporting
    bug_report: str | None
    execution_log_path: str | None

    # control
    human_approved: bool | None
    halted_reason: str | None
