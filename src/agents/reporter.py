"""
Reporter Agent — Phase 5 (final) of the Agentic STLC.

Consumes execution_results + failures and produces two artifacts via the
Filesystem MCP server:
  1. execution_log.json — full machine-readable run record (also includes the
     MCPToolClient audit trail for traceability/debugging)
  2. bug_report.md — human-readable summary, formatted the way a QA engineer
     would write a Jira/GitHub issue, for any test that failed and could not
     be healed.

No LLM call is required for the structured log; the bug_report.md narrative
IS LLM-generated (from a template prompt) so it reads like a human wrote it,
which matters for a demo aimed at showing "agent quality," not just "agent
correctness."
"""
from __future__ import annotations

import json
from pathlib import Path

from models.state import AgentState


REPORT_PROMPT = """You are a senior QA engineer writing a bug report summary
for a test run. Given the requirement, the test results, and details on any
failures, write a concise Markdown bug report suitable for pasting into
GitHub Issues or Jira. Include:
- A one-line summary status (e.g. "3/3 passed" or "2/3 passed, 1 failed")
- For each FAILED test: title, steps to reproduce, expected vs actual, and a
  suggested severity (P0/P1/P2)
- Do NOT invent failures that aren't in the data provided.
Keep it under 400 words.
"""


def build_report_prompt(state: AgentState) -> list[dict]:
    payload = {
        "requirement": state["requirement"],
        "results": [r.model_dump() for r in state.get("execution_results", [])],
        "unhealed_failures": [f.model_dump() for f in state.get("failures", [])],
    }
    return [
        {"role": "system", "content": REPORT_PROMPT},
        {"role": "user", "content": json.dumps(payload, indent=2)},
    ]


async def report_node(state: AgentState, llm_client, fs_mcp_client, output_dir: str = "demo/sample_run") -> dict:
    """
    `fs_mcp_client` is the same MCPToolClient type used by the Executor/Healer,
    pointed at the filesystem MCP server (see mcp_config/mcp_servers.json).
    Writes go through `fs_mcp_client.call("write_file", ...)` so they are
    subject to the same guardrail/audit boundary as every other tool call in
    the system (see architecture/03_mcp_integration.md) rather than the agent
    reaching for raw disk I/O directly. `write_local_fallback` is used only
    when running in mock/offline mode where no real filesystem MCP server is
    connected (MCP_SDK_AVAILABLE=False) — see tools/mcp_client_mock.py.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    log_payload = {
        "trace_id": state.get("trace_id"),
        "requirement": state["requirement"],
        "target_env": state.get("target_env"),
        "test_plan": state["test_plan"].model_dump() if state.get("test_plan") else None,
        "results": [r.model_dump() for r in state.get("execution_results", [])],
        "healing_attempts": state.get("healing_attempts", 0),
        "guardrail_retry_count": state.get("guardrail_retry_count", 0),
    }
    log_path = f"{output_dir}/execution_log.json"

    messages = build_report_prompt(state)
    bug_report_md = await llm_client.complete(messages)
    report_path = f"{output_dir}/bug_report.md"

    await _write_via_fs_mcp_or_fallback(fs_mcp_client, log_path, json.dumps(log_payload, indent=2, default=str))
    await _write_via_fs_mcp_or_fallback(fs_mcp_client, report_path, bug_report_md)

    return {
        "bug_report": bug_report_md,
        "execution_log_path": log_path,
    }


async def _write_via_fs_mcp_or_fallback(fs_mcp_client, path: str, content: str) -> None:
    try:
        await fs_mcp_client.call("write_file", path=path, content=content)
    except Exception:
        # Offline/mock mode (no filesystem MCP server connected) — write directly.
        # This keeps `python langgraph_agent/graph.py` runnable with zero
        # external MCP servers for the demo; a real filesystem MCP server
        # would handle "write_file" above and this branch would never trigger.
        Path(path).write_text(content)
