"""
MCPToolClient — the single boundary between agents and MCP servers.

Responsibilities:
  1. Launch/connect to configured MCP servers (Selenium, Filesystem) over stdio.
  2. Expose a uniform `.call(tool_name, **kwargs)` used by every agent.
  3. Enforce guardrails (tool allow-list, URL allow-list, script deny-list, rate limit)
     BEFORE any call reaches the MCP server — see guardrails/mcp_guardrails.py.
  4. Append every call + result to the audit trail (execution_log.json).

This module deliberately contains no LLM logic — it is pure plumbing so that
agent code never needs to know about JSON-RPC/stdio transport details.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guardrails.mcp_guardrails import GuardrailViolation, check_tool_call

try:
    # Real MCP SDK — used when actually running against a live MCP server.
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - allows offline/demo mode without the SDK installed
    MCP_SDK_AVAILABLE = False


@dataclass
class ToolCallRecord:
    call_id: str
    tool: str
    args: dict[str, Any]
    result: Any
    ok: bool
    duration_ms: int
    timestamp: float = field(default_factory=time.time)


class MCPToolClient:
    """
    Thin, guardrailed wrapper around one or more MCP servers.

    Usage:
        client = MCPToolClient.from_config("mcp_config/mcp_servers.json", target_env="sandbox")
        await client.connect()
        result = await client.call("navigate", url="https://example.com/login")
        await client.close()
    """

    def __init__(self, config: dict, target_env: str = "sandbox", use_mock: bool | None = None):
        self.config = config
        self.target_env = target_env
        self.use_mock = (
            any(server.get("command") == "mock" for server in config.get("mcp_servers", []))
            if use_mock is None
            else use_mock
        )
        self.audit_log: list[ToolCallRecord] = []
        self._sessions: dict[str, Any] = {}
        self._max_calls_per_test = config.get("guardrails", {}).get("max_tool_calls_per_test", 40)
        self._call_count = 0

    @classmethod
    def from_config(
        cls, config_path: str, target_env: str = "sandbox", use_mock: bool | None = None
    ) -> "MCPToolClient":
        with open(config_path) as f:
            config = json.load(f)
        return cls(config, target_env=target_env, use_mock=use_mock)

    async def connect(self) -> None:
        """Start the configured MCP server subprocesses and open sessions."""
        if self.use_mock or not MCP_SDK_AVAILABLE:
            # Demo/offline mode: mcp_client_mock.py substitutes a fake DOM-backed client.
            return
        for server in self.config["mcp_servers"]:
            params = StdioServerParameters(
                command=server["command"],
                args=server.get("args", []),
                env=server.get("env"),
            )
            read, write = await stdio_client(params).__aenter__()
            session = await ClientSession(read, write).__aenter__()
            await session.initialize()
            self._sessions[server["name"]] = session

    async def call(self, tool_name: str, **kwargs) -> Any:
        """
        Guardrailed, audited tool call.

        Raises GuardrailViolation if the call is blocked before it ever reaches
        the MCP server (e.g. disallowed URL, destructive script, tool not on
        the allow-list, or per-test call budget exceeded).
        """
        self._call_count += 1
        if self._call_count > self._max_calls_per_test:
            raise GuardrailViolation(
                f"Per-test MCP call budget exceeded ({self._max_calls_per_test}). "
                "Likely an infinite retry loop — halting."
            )

        # Deterministic guardrail check BEFORE dispatch
        check_tool_call(tool_name, kwargs, target_env=self.target_env, config=self.config)

        call_id = str(uuid.uuid4())[:8]
        start = time.time()
        try:
            result = await self._dispatch(tool_name, kwargs)
            ok = True
        except Exception as e:  # noqa: BLE001 - we want to log and re-raise
            result = {"error": str(e)}
            ok = False
            duration_ms = int((time.time() - start) * 1000)
            self.audit_log.append(ToolCallRecord(call_id, tool_name, kwargs, result, ok, duration_ms))
            raise

        duration_ms = int((time.time() - start) * 1000)
        self.audit_log.append(ToolCallRecord(call_id, tool_name, kwargs, result, ok, duration_ms))
        return result

    async def _dispatch(self, tool_name: str, kwargs: dict) -> Any:
        # Validate the tool is declared on some configured server even in mock
        # mode — this is what makes an unrecognized tool name fail loudly
        # instead of silently no-op-ing, in both real and demo runs.
        server_name = self._resolve_server_for_tool(tool_name)

        if self.use_mock or not MCP_SDK_AVAILABLE:
            from tools.mcp_client_mock import MockSeleniumBackend
            return await MockSeleniumBackend.instance().call(tool_name, kwargs)

        session = self._sessions[server_name]
        response = await session.call_tool(tool_name, kwargs)
        return response

    def _resolve_server_for_tool(self, tool_name: str) -> str:
        for server in self.config["mcp_servers"]:
            if tool_name in server.get("tools", []):
                return server["name"]
        raise GuardrailViolation(f"Tool '{tool_name}' is not exposed by any configured MCP server")

    def write_audit_log(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump([r.__dict__ for r in self.audit_log], f, indent=2, default=str)

    async def close(self) -> None:
        for session in self._sessions.values():
            await session.__aexit__(None, None, None)
        self._sessions.clear()
