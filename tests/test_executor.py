"""
Unit tests for src/agents/executor.py — failure classification and routing.
Uses the mock MCP backend, so runs with zero external dependencies beyond
langgraph/pydantic. Run: pytest tests/test_executor.py -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agents.executor import classify_failure, route_after_execution, run_single_test
from models.state import TestCase, TestFailure, TestStep
from tools.mcp_client import MCPToolClient


CONFIG = {
    "mcp_servers": [{
        "name": "selenium", "command": "mock", "args": [],
        "tools": ["navigate", "find_element", "click", "send_keys", "get_text", "get_page_source"],
    }],
    "guardrails": {
        "allowed_tools": ["navigate", "find_element", "click", "send_keys", "get_text", "get_page_source"],
        "allowed_domains": {"sandbox": ["demo.aiqef.local"]},
        "max_tool_calls_per_test": 40,
    },
}


@pytest.mark.parametrize("msg,expected", [
    ("NoSuchElementException: no element for css='#btn'", "locator_not_found"),
    ("ElementNotFoundError: missing", "locator_not_found"),
    ("TimeoutException: timed out after 5s", "timeout"),
    ("Expected 'foo' in actual 'bar'", "assertion_failed"),
])
def test_classify_failure(msg, expected):
    assert classify_failure(msg) == expected


def test_route_after_execution_heals_on_locator_failure():
    state = {"failures": [TestFailure(test_id="TC-001", step_index=2, reason="locator_not_found", original_locator="#old")],
             "healing_attempts": 0}
    assert route_after_execution(state) == "heal"


def test_route_after_execution_stops_healing_after_two_attempts():
    state = {"failures": [TestFailure(test_id="TC-001", step_index=2, reason="locator_not_found", original_locator="#old")],
             "healing_attempts": 2}
    assert route_after_execution(state) == "report"


def test_route_after_execution_reports_pure_assertion_failure():
    state = {"failures": [], "healing_attempts": 0}
    assert route_after_execution(state) == "report"


@pytest.mark.asyncio
async def test_run_single_test_passes_happy_path():
    from tools.mcp_client_mock import FAKE_DOM, MockSeleniumBackend
    MockSeleniumBackend._instance = None  # reset singleton between tests
    FAKE_DOM["https://demo.aiqef.local/login"]["elements"][("css", ".error-banner")]["text"] = ""

    client = MCPToolClient(CONFIG, target_env="sandbox")
    test_case = TestCase(
        id="TC-001", title="Login fails with wrong password", priority="P0",
        steps=[
            TestStep(action="navigate", value="https://demo.aiqef.local/login"),
            TestStep(action="send_keys", by="id", value="username", input_text="demo_user"),
            TestStep(action="send_keys", by="id", value="password", input_text="wrong-password-123"),
            TestStep(action="click", by="css", value="button[data-testid='submit']"),
            TestStep(action="get_text", by="css", value=".error-banner", expected="Invalid username or password"),
        ],
    )
    result, failure = await run_single_test(test_case, client)
    assert result.status == "passed"
    assert failure is None


@pytest.mark.asyncio
async def test_run_single_test_fails_on_stale_locator():
    from tools.mcp_client_mock import MockSeleniumBackend
    MockSeleniumBackend._instance = None

    client = MCPToolClient(CONFIG, target_env="sandbox")
    test_case = TestCase(
        id="TC-001", title="Login fails with wrong password", priority="P0",
        steps=[
            TestStep(action="navigate", value="https://demo.aiqef.local/login"),
            TestStep(action="click", by="css", value="#submit-btn-old"),  # stale locator
        ],
    )
    result, failure = await run_single_test(test_case, client)
    assert result.status == "failed"
    assert failure.reason == "locator_not_found"
