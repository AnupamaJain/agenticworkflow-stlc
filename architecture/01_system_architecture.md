# System Architecture

## 1. High-Level Overview

The **AI Quality Engineering Framework (AI-QEF)** is a multi-agent system that automates
the full Software Testing Life Cycle (STLC) — from a plain-English requirement to an
executed test run and a structured bug report — using **LangGraph** for orchestration,
the **Model Context Protocol (MCP)** for tool access, and **Selenium MCP Server** for
real browser automation.

```mermaid
flowchart TB
    subgraph Input["📝 Input Layer"]
        REQ[Requirement / User Story]
    end

    subgraph Orchestration["🧠 LangGraph Orchestration Layer"]
        direction TB
        PLANNER[Planner Agent<br/>test_plan_node]
        GENERATOR[Test Generator Agent<br/>test_generation_node]
        REVIEWER[Guardrail Reviewer<br/>guardrail_node]
        EXECUTOR[Execution Agent<br/>test_execution_node]
        HEALER[Self-Healing Agent<br/>self_heal_node]
        REPORTER[Bug Reporter Agent<br/>report_node]
    end

    subgraph MCP["🔌 MCP Layer"]
        SELENIUM_MCP[Selenium MCP Server]
        FS_MCP[Filesystem MCP Server]
    end

    subgraph Target["🌐 System Under Test"]
        BROWSER[Real Browser<br/>Chrome/Firefox via WebDriver]
        SUT[Target Web Application]
    end

    subgraph Evaluation["📊 Evaluation & Observability"]
        EVAL[Eval Harness<br/>LLM-as-judge + deterministic checks]
        TRACE[LangSmith / Trace Store]
    end

    subgraph Output["📦 Output Layer"]
        TESTPLAN[test_plan.json]
        TESTCODE[generated pytest suite]
        RUNLOG[execution_log.json]
        BUGREPORT[bug_report.md]
    end

    REQ --> PLANNER
    PLANNER --> TESTPLAN
    PLANNER --> GENERATOR
    GENERATOR --> TESTCODE
    GENERATOR --> REVIEWER
    REVIEWER -- "approved" --> EXECUTOR
    REVIEWER -- "rejected: regenerate" --> GENERATOR
    EXECUTOR --> SELENIUM_MCP
    SELENIUM_MCP --> BROWSER
    BROWSER --> SUT
    EXECUTOR -- "locator/assertion failure" --> HEALER
    HEALER -- "patched test" --> EXECUTOR
    HEALER -- "cannot heal" --> REPORTER
    EXECUTOR -- "pass/fail results" --> REPORTER
    REPORTER --> FS_MCP
    FS_MCP --> RUNLOG
    FS_MCP --> BUGREPORT
    PLANNER -.-> TRACE
    GENERATOR -.-> TRACE
    EXECUTOR -.-> TRACE
    EVAL -.-> TRACE

    style Orchestration fill:#1a1a2e,stroke:#e94560,color:#fff
    style MCP fill:#16213e,stroke:#0f3460,color:#fff
    style Target fill:#0f3460,stroke:#533483,color:#fff
    style Evaluation fill:#222,stroke:#888,color:#fff
```

## 2. Design Principles

| Principle | Why it matters |
|---|---|
| **Agent per STLC phase, not one mega-prompt** | Mirrors real QA process (plan → design → execute → report), makes each step independently testable/evaluable, keeps prompts small and reviewable |
| **MCP as the tool boundary** | Agents never call Selenium directly — they call MCP tools. This decouples "what the LLM decides" from "how automation executes," and lets you swap Selenium MCP for Playwright MCP without touching agent logic |
| **Guardrail node before execution** | An LLM-generated test never touches a real browser unversioned/unreviewed — a deterministic + LLM-judge guardrail checks for destructive actions, PII, scope creep |
| **Self-healing over hard failure** | Locator drift is the #1 cause of flaky UI suites; the healer agent re-inspects the DOM via MCP and patches the locator instead of just failing |
| **Everything is a typed state object** | LangGraph `AgentState` (TypedDict/Pydantic) is the single source of truth passed between nodes — no hidden global state |
| **Human-in-the-loop checkpoint** | Optional interrupt before execution against non-sandbox targets (see `langgraph_agent/graph.py`) |

## 3. Component Map

```mermaid
graph LR
    subgraph "src/"
        A[agents/planner.py]
        B[agents/test_generator.py]
        C[agents/guardrail.py]
        D[agents/executor.py]
        E[agents/self_healer.py]
        F[agents/reporter.py]
        G[graph.py<br/>LangGraph StateGraph]
        H[models/state.py<br/>AgentState schema]
        I[tools/mcp_client.py]
    end

    G --> A & B & C & D & E & F
    A & B & C & D & E & F --> H
    D --> I
    E --> I
    I --> J[(Selenium MCP Server)]

    style G fill:#e94560,color:#fff
```

## 4. Why LangGraph over a plain agent loop

- **Explicit cyclic control flow**: generation ↔ guardrail ↔ regeneration, and execution ↔
  self-healing ↔ re-execution are natural graph cycles, not easily expressed as a linear chain.
- **Checkpointing**: LangGraph's checkpointer lets a run pause at the human-approval gate and
  resume later — useful for CI where execution against staging needs sign-off.
- **Conditional edges** map 1:1 to QA decision points ("did the test pass guardrail review?",
  "is the failure a real bug or a broken locator?").

See [`02_agent_workflow.md`](./02_agent_workflow.md) for the detailed per-node state diagram
and [`03_mcp_integration.md`](./03_mcp_integration.md) for how MCP tool calls are wired in.
