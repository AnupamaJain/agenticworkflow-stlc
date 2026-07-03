# Demo — Full Agentic STLC Run

## 1. What this demo shows

A single command runs the **entire agentic STLC** end-to-end, with zero
external dependencies (no API key, no real browser, no live MCP server
required) — because it uses a scripted `FakeLLMClient` and a mock Selenium
MCP backend that simulates a real DOM, including a **deliberately broken
locator** so the Self-Healing Agent has something real to demonstrate.

```bash
pip install -r requirements.txt
python langgraph_agent/graph.py
```

## 2. What happens, step by step

1. **Requirement in:**
   > "Verify that the login page rejects an incorrect password and shows the
   > error message 'Invalid username or password'."

2. **Planner Agent** decomposes this into a structured test plan — 1 P0
   scenario, explicit scope/out-of-scope, risk notes. See
   [`sample_run/execution_log.json`](./sample_run/execution_log.json) →
   `test_plan`.

3. **Test Generator Agent** writes 5 executable MCP tool-call steps: navigate,
   fill username, fill password, click submit, assert error text.

4. **Guardrail Agent** reviews the generated test — approves it (fake
   credentials, in-scope, has a real assertion).

5. **Execution Agent** runs it against the mock browser. Step 4 (click submit)
   **fails** — the mock DOM's submit button locator was renamed from
   `#submit-btn-old` to `button[data-testid='submit']` (simulating a real
   frontend refactor).

6. **Self-Healing Agent** is triggered automatically: pulls the current DOM
   via `get_page_source`, identifies the renamed button, patches the test.

7. **Execution Agent retries** — this time it passes, error banner correctly
   shows `"Invalid username or password"`.

8. **Reporter Agent** writes [`sample_run/bug_report.md`](./sample_run/bug_report.md)
   and [`sample_run/execution_log.json`](./sample_run/execution_log.json) —
   noting this was a test-maintenance event, not a product defect, and
   recommending the locator be updated at the source so future runs don't
   need to re-heal it.

## 3. Sample output

```
=== Run complete (trace_id=0d7e1a86) ===
Bug report written to: demo/sample_run/execution_log.json
  TC-001: passed (5 steps, 287ms)
```

Full artifacts from this exact run:
- [`sample_run/execution_log.json`](./sample_run/execution_log.json) — structured run record
- [`sample_run/mcp_audit_log.json`](./sample_run/mcp_audit_log.json) — every single MCP tool call, args, result, timing (including the failed one)
- [`sample_run/bug_report.md`](./sample_run/bug_report.md) — human-readable summary

## 4. Running with a real LLM + real Selenium MCP server

```bash
pip install mcp anthropic selenium
export ANTHROPIC_API_KEY=sk-...
# start a real selenium-mcp-server per mcp_config/mcp_servers.json, then:
```
```python
from langgraph_agent.graph import build_graph, run_demo
from tools.real_llm_client import RealLLMClient
# swap FakeLLMClient() for RealLLMClient() inside run_demo(), or call build_graph() directly
```

No agent code changes are needed — only the client injected into `build_graph()`
changes, which is the entire point of the MCP + clean-interface design (see
[`architecture/03_mcp_integration.md`](../architecture/03_mcp_integration.md)).

## 5. Talking points for interviews / walkthroughs

- **"Why LangGraph and not a simple chain?"** → point to the guardrail↔generate
  and execute↔heal cycles — genuinely cyclic control flow, not linear.
- **"How do you keep an LLM-generated test from doing something destructive?"**
  → two-layer guardrail: deterministic MCP-boundary checks (URL allow-list,
  script deny-list) that run on *every* tool call, plus an LLM reviewer that
  runs *once* per generated test for semantic checks like scope creep.
- **"How do you handle flaky UI tests?"** → this demo's whole narrative: a
  locator drift, self-healed, correctly *not* reported as a bug because it's
  a test-maintenance issue, not a product defect.
- **"How do you evaluate agent quality, not just correctness?"** → point to
  `evaluation/guardrail_eval_cases.jsonl` — a labeled precision/recall eval
  set that gates CI, so a prompt change that silently weakens the guardrail
  gets caught before merge.
