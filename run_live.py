"""
Live runner using the unified LLM Gateway Client.
Executes the full LangGraph Agentic STLC.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

# Setup paths
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

from langgraph_agent.graph import build_graph
from tools.real_llm_client import RealLLMClient
from tools.mcp_client import MCPToolClient
from models.state import AgentState


async def main():
    # Verify we have at least one valid key configured
    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if not any([groq_key, gemini_key, anthropic_key]):
        print("ERROR: No API key found in environment variables.")
        print("Please export at least one of the following:")
        print("  export GROQ_API_KEY=\"your-groq-key\"")
        print("  export GEMINI_API_KEY=\"your-gemini-key\"")
        print("  export ANTHROPIC_API_KEY=\"your-anthropic-key\"")
        sys.exit(1)

    # 1. Instantiate the LLM Gateway Client
    # It will automatically detect and use the active key
    llm_client = RealLLMClient()
    print(f"LLM Gateway initialized using provider: {llm_client.provider.upper()} (Model: {llm_client.model})")

    # 2. Setup the MCP Client
    # We use use_mock=True here so the browser logic is simulated and runs offline
    # Change use_mock=False if you have a real Selenium server running locally
    mcp_client = MCPToolClient.from_config(
        config_path=str(ROOT / "mcp_config" / "mcp_servers.json"),
        target_env="sandbox",
        use_mock=True
    )
    await mcp_client.connect()

    # 3. Build the workflow graph
    app = build_graph(llm_client, mcp_client)

    # 4. Invoke with a requirement
    initial_state: AgentState = {
        "requirement": (
            "Verify that the login page rejects an incorrect password and shows "
            "the error message 'Invalid username or password'."
        ),
        "target_env": "sandbox",
        "trace_id": str(uuid.uuid4())[:8],
    }
    config = {"configurable": {"thread_id": initial_state["trace_id"]}}

    print(f"Starting pipeline with trace_id: {initial_state['trace_id']}")
    result = await app.ainvoke(initial_state, config=config)

    # 5. Output summary
    print("\n=== Run complete ===")
    print(f"Bug report written to: demo/sample_run/bug_report.md")
    print(f"Execution log written to: {result.get('execution_log_path')}")
    
    for r in result.get("execution_results", []):
        print(f"  {r.test_id}: {r.status} ({r.steps_executed} steps, {r.duration_ms}ms)")


if __name__ == "__main__":
    asyncio.run(main())
