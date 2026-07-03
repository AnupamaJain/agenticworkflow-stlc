# Agentic STLC — Methodology

## 1. Mapping traditional STLC phases to agents

| Traditional STLC Phase | Human activity | Agent in this system | Node |
|---|---|---|---|
| Requirement Analysis | QA reads user story, asks clarifying questions | *(human-provided input — not automated)* | — |
| Test Planning | QA lead writes test plan: scope, scenarios, priorities | **Planner Agent** | `plan_node` |
| Test Case Design | SDET writes detailed steps/scripts | **Test Generator Agent** | `generate_node` |
| Test Case Review | Peer review / lead sign-off before automation runs | **Guardrail Agent** (+ optional human gate for non-sandbox) | `guardrail_node`, `human_approval` |
| Test Execution | Run automation suite, observe results | **Execution Agent** | `execute_node` |
| Defect Triage (locator drift) | Engineer investigates why a test broke, fixes the script | **Self-Healing Agent** | `heal_node` |
| Defect Reporting | QA files a bug with repro steps | **Reporter Agent** | `report_node` |

## 2. What's deliberately NOT automated, and why

- **Requirement Analysis is not an agent.** Turning a vague stakeholder
  request into a testable requirement benefits from human context
  (business priorities, what "done" means for this team) that an LLM
  can't reliably infer. This system starts from an already-written
  requirement, same as how a QA team receives a ticket.
- **Non-sandbox execution always has a human gate.** See
  `human_approval_node` in `langgraph_agent/graph.py` — a `staging` or
  `production` target_env always interrupts for human sign-off before any
  MCP tool call touches that environment, regardless of guardrail approval.
- **The Guardrail Agent can reject, but never silently edits a test.** If
  it disapproves, control returns to the Generator to redo the work — the
  guardrail's role is judgment, not authorship, keeping a clean separation
  of concerns (and making the guardrail's own behavior easier to eval, see
  `evaluation/README.md`).

## 3. Why this ordering (and not, e.g., generate-then-plan)

Planning before generation mirrors how experienced QA teams actually work —
and has a concrete engineering payoff: the Planner's output is small,
human-reviewable JSON (scope + scenario titles + priorities) that's cheap to
validate before spending tokens/tool calls on writing and reviewing full
executable steps. If a requirement is ambiguous, that shows up as a vague or
overly-broad test plan **before** any browser automation is generated —
catching the problem at the cheapest possible point in the pipeline.

## 4. Bug vs. flake vs. tooling-failure — how this system tells them apart

A common failure of "AI testing agent" demos is treating every red result the
same way. This system explicitly classifies failures (`FailureReason` in
`src/models/state.py`) into three categories with different handling:

| Category | Example | System response |
|---|---|---|
| **Locator drift** (`locator_not_found`) | A `data-testid` was renamed | Route to Self-Healer; if healed, this is a **test-maintenance note** in the bug report, not a defect |
| **Timeout** (`timeout`) | Page loaded slower than expected | Route to Self-Healer first (re-check element with a fresh wait); if it heals, treated as environmental flakiness, not a defect |
| **Real assertion failure** (`assertion_failed`) | Error banner text doesn't match, or is empty | Never routed to Healer — straight to Reporter as a genuine product defect |

This distinction is why `route_after_execution` (in `executor.py`) only sends
`locator_not_found`/`timeout` to the Healer — an assertion failure means the
application genuinely behaved differently than expected, and "healing" that
would mean silently rewriting the test to match broken behavior, which is
exactly the failure mode a guardrail-conscious system must avoid.

## 5. Extending this to more of the STLC

Natural next phases to add (not built here, but the graph is structured to
make each a straightforward new node + conditional edge):
- **Regression impact analysis** — given a code diff, which existing
  generated tests are most likely affected? (would sit between Planning and
  Generation)
- **Test data management agent** — generate realistic-but-fake fixture data
  per scenario instead of hardcoding it in prompts
- **Flakiness scoring** — track healing frequency per test over time and
  flag tests that need a human to redesign the locator strategy, not just
  keep auto-healing
