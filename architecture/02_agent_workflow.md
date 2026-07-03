# Agent Workflow — LangGraph State Machine

## 1. Node-Level State Diagram

This is the actual graph implemented in [`langgraph_agent/graph.py`](../langgraph_agent/graph.py).

```mermaid
stateDiagram-v2
    [*] --> Plan

    Plan: 🧠 plan_node\n(Planner Agent)\nrequirement → test_plan
    Generate: ✍️ generate_node\n(Test Generator)\ntest_plan → pytest code
    Guardrail: 🛡️ guardrail_node\n(Guardrail Reviewer)\nvalidate generated test
    Execute: ▶️ execute_node\n(Execution Agent)\nrun via Selenium MCP
    Heal: 🩹 heal_node\n(Self-Healing Agent)\nre-locate & patch
    Report: 📄 report_node\n(Bug Reporter)\nsummarize + file report
    HumanGate: 🧍 human_approval\n(interrupt, optional)

    Plan --> Generate: test_plan produced
    Generate --> Guardrail: candidate test code

    Guardrail --> Generate: rejected (max 3 retries)\nfeedback appended to state
    Guardrail --> HumanGate: approved + non-sandbox target
    Guardrail --> Execute: approved + sandbox target

    HumanGate --> Execute: human approves
    HumanGate --> [*]: human rejects (run halted)

    Execute --> Report: all steps passed
    Execute --> Heal: locator/timeout failure detected
    Execute --> Report: assertion failure (real bug, not flaky)

    Heal --> Execute: locator patched, retry (max 2)
    Heal --> Report: cannot heal after 2 attempts

    Report --> [*]: bug_report.md + execution_log.json written
```

## 2. AgentState Schema

Single typed object threaded through every node (`src/models/state.py`):

```python
class AgentState(TypedDict):
    requirement: str                    # raw input
    test_plan: TestPlan | None          # structured plan from Planner
    generated_tests: list[TestCase]     # pytest test cases as structured objects
    guardrail_verdict: GuardrailVerdict | None
    guardrail_retry_count: int
    execution_results: list[TestResult]
    healing_attempts: int
    failures: list[TestFailure]
    bug_report: str | None
    target_env: Literal["sandbox", "staging", "production"]
    trace_id: str
```

## 3. Conditional Edge Logic

| Edge decision | Function | Logic |
|---|---|---|
| Guardrail → Generate / HumanGate / Execute | `route_after_guardrail()` | If `verdict.approved is False` and `retry_count < 3` → back to Generate. If approved and `target_env != "sandbox"` → HumanGate. Else → Execute. |
| Execute → Heal / Report | `route_after_execution()` | If failure `reason == "locator_not_found"` or `"timeout"` and `healing_attempts < 2` → Heal. Otherwise → Report. |
| Heal → Execute / Report | `route_after_heal()` | If healer returns a patched locator → Execute (increment `healing_attempts`). If healer returns `None` (no confident fix) → Report. |

## 4. Sequence Diagram — Happy Path Demo Run

```mermaid
sequenceDiagram
    actor User
    participant Planner
    participant Generator
    participant Guardrail
    participant Executor
    participant MCP as Selenium MCP Server
    participant Browser
    participant Reporter

    User->>Planner: "Verify login fails with wrong password on the demo site"
    Planner->>Planner: Decompose into test scenarios + acceptance criteria
    Planner-->>Generator: TestPlan(3 scenarios)
    Generator->>Generator: Generate pytest + Selenium MCP tool calls
    Generator-->>Guardrail: candidate test code
    Guardrail->>Guardrail: Check for destructive ops, scope, PII
    Guardrail-->>Executor: approved
    loop for each test case
        Executor->>MCP: navigate(url)
        MCP->>Browser: WebDriver command
        Executor->>MCP: find_element + send_keys(credentials)
        Executor->>MCP: click(login_button)
        Executor->>MCP: get_text(error_banner)
        MCP-->>Executor: "Invalid username or password"
        Executor->>Executor: assert expected == actual
    end
    Executor-->>Reporter: results: 3 passed, 0 failed
    Reporter->>Reporter: Render execution_log.json + summary
    Reporter-->>User: ✅ Test run complete — report attached
```

## 5. Sequence Diagram — Self-Healing Path

```mermaid
sequenceDiagram
    participant Executor
    participant MCP as Selenium MCP Server
    participant Healer
    participant Reporter

    Executor->>MCP: find_element(css="#submit-btn-old")
    MCP-->>Executor: ElementNotFoundError
    Executor->>Healer: failure(locator="#submit-btn-old", step="click submit")
    Healer->>MCP: get_page_source()
    MCP-->>Healer: current DOM
    Healer->>Healer: LLM proposes new locator from DOM diff
    Healer-->>Executor: patched_locator="button[data-testid='submit']"
    Executor->>MCP: find_element(css="button[data-testid='submit']")
    MCP-->>Executor: element found ✅
    Executor->>Executor: resume test from patched step
    Note over Executor,Reporter: If healing fails twice, escalate to Reporter as a real defect, not silently retried forever
```
