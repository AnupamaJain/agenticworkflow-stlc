"""
LangGraph StateGraph wiring for the Agentic STLC.

This is the file that turns the individual agent nodes (src/agents/*.py) into
an actual executable, cyclic workflow. Matches the state diagram in
architecture/02_agent_workflow.md exactly — if you change one, change the other.

Run this directly for a full demo:  python langgraph_agent/graph.py
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agents.executor import execute_node, route_after_execution
from agents.guardrail import guardrail_node, route_after_guardrail
from agents.planner import plan_node
from agents.reporter import report_node
from agents.self_healer import heal_node
from agents.test_generator import generate_node
from models.state import AgentState
from tools.mcp_client import MCPToolClient


def human_approval_node(state: AgentState) -> dict:
    """
    Interrupt point for non-sandbox targets. LangGraph pauses here
    (see `interrupt_before=["human_approval"]` in build_graph) and resumes
    when the caller updates state with human_approved=True/False.
    """
    return {}


def route_after_human_approval(state: AgentState) -> str:
    if state.get("human_approved"):
        return "execute"
    return "halted"


def halted_node(state: AgentState) -> dict:
    return {"halted_reason": "Human reviewer did not approve execution against non-sandbox target."}


def build_graph(llm_client, mcp_client: MCPToolClient, fs_mcp_client=None):
    """
    Wires nodes with their required clients bound via closures, so the graph
    itself has a clean `AgentState -> AgentState` node signature (what
    LangGraph expects) while agents stay unit-testable with injected fakes.
    """
    fs_mcp_client = fs_mcp_client or mcp_client
    graph = StateGraph(AgentState)

    async def run_plan(state: AgentState) -> dict:
        return await plan_node(state, llm_client)

    async def run_generate(state: AgentState) -> dict:
        return await generate_node(state, llm_client)

    async def run_guardrail(state: AgentState) -> dict:
        return await guardrail_node(state, llm_client)

    async def run_execute(state: AgentState) -> dict:
        return await execute_node(state, mcp_client)

    async def run_heal(state: AgentState) -> dict:
        return await heal_node(state, llm_client, mcp_client)

    async def run_report(state: AgentState) -> dict:
        return await report_node(state, llm_client, fs_mcp_client)

    graph.add_node("plan", run_plan)
    graph.add_node("generate", run_generate)
    graph.add_node("guardrail", run_guardrail)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("halted", halted_node)
    graph.add_node("execute", run_execute)
    graph.add_node("heal", run_heal)
    graph.add_node("report", run_report)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "generate")
    graph.add_edge("generate", "guardrail")

    graph.add_conditional_edges(
        "guardrail", route_after_guardrail,
        {"generate": "generate", "human_approval": "human_approval", "execute": "execute", "report": "report"},
    )
    graph.add_conditional_edges(
        "human_approval", route_after_human_approval,
        {"execute": "execute", "halted": "halted"},
    )
    graph.add_conditional_edges(
        "execute", route_after_execution,
        {"heal": "heal", "report": "report"},
    )
    graph.add_edge("heal", "execute")
    graph.add_edge("report", END)
    graph.add_edge("halted", END)

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer, interrupt_before=["human_approval"])


async def run_demo(requirement: str, target_env: str = "sandbox"):
    from tools.fake_llm_client import FakeLLMClient  # deterministic, scripted demo responses

    llm_client = FakeLLMClient()
    mcp_client = MCPToolClient.from_config(
        str(ROOT / "mcp_config" / "mcp_servers.json"),
        target_env=target_env,
        use_mock=True,
    )
    await mcp_client.connect()

    app = build_graph(llm_client, mcp_client)

    initial_state: AgentState = {
        "requirement": requirement,
        "target_env": target_env,
        "trace_id": str(uuid.uuid4())[:8],
    }
    config = {"configurable": {"thread_id": initial_state["trace_id"]}}

    result = await app.ainvoke(initial_state, config=config)

    if target_env != "sandbox" and result.get("halted_reason") is None and not result.get("bug_report"):
        # graph paused at human_approval interrupt — auto-approve for demo purposes
        await app.aupdate_state(config, {"human_approved": True})
        result = await app.ainvoke(None, config=config)

    mcp_client.write_audit_log("demo/sample_run/mcp_audit_log.json")

    print(f"\n=== Run complete (trace_id={initial_state['trace_id']}) ===")
    print("Bug report written to: demo/sample_run/bug_report.md")
    print(f"Execution log written to: {result.get('execution_log_path')}")
    for r in result.get("execution_results", []):
        print(f"  {r.test_id}: {r.status} ({r.steps_executed} steps, {r.duration_ms}ms)")

    return result


if __name__ == "__main__":
    requirement = (
        "Verify that the login page rejects an incorrect password and shows "
        "the error message 'Invalid username or password'."
    )
    asyncio.run(run_demo(requirement, target_env="sandbox"))
