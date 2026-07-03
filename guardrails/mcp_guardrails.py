"""
Deterministic guardrails enforced at the MCP tool-call boundary.

These run BEFORE every MCP call (see src/tools/mcp_client.py: MCPToolClient.call()).
They are intentionally simple, fast, and non-LLM — the point of a guardrail
layer is to be something you can reason about and unit test exhaustively,
unlike the LLM agents themselves. LLM-based review lives separately in
guardrails/llm_guardrail_reviewer.py and runs once per generated test, not
per tool call.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse


class GuardrailViolation(Exception):
    """Raised when a tool call is blocked before reaching the MCP server."""


# Scripts containing any of these patterns are always blocked, regardless of
# config, because they are destructive or exfiltration-shaped regardless of
# target environment.
HARD_DENY_SCRIPT_PATTERNS = [
    r"localStorage\.clear",
    r"sessionStorage\.clear",
    r"document\.cookie\s*=",
    r"fetch\([^)]*DELETE",
    r"fetch\([^)]*method:\s*['\"]DELETE",
    r"XMLHttpRequest",
    r"window\.location\s*=",
    r"\.remove\(\)",
    r"DROP\s+TABLE",
    r"eval\(",
]


def check_tool_call(tool_name: str, args: dict, target_env: str, config: dict) -> None:
    """Raises GuardrailViolation if the call should be blocked. Returns None if OK."""
    _check_tool_allow_list(tool_name, config)

    if tool_name == "navigate":
        _check_url_allow_list(args.get("url", ""), target_env, config)

    if tool_name == "execute_script":
        _check_script_deny_list(args.get("script", ""))

    if tool_name in ("send_keys",):
        _check_no_real_secrets(args.get("input_text", ""))


def _check_tool_allow_list(tool_name: str, config: dict) -> None:
    allow_list: list[str] = config.get("guardrails", {}).get("allowed_tools", [])
    if allow_list and tool_name not in allow_list:
        raise GuardrailViolation(
            f"Tool '{tool_name}' is not on the guardrail allow-list {allow_list}"
        )


def _check_url_allow_list(url: str, target_env: str, config: dict) -> None:
    domains: dict[str, list[str]] = config.get("guardrails", {}).get("allowed_domains", {})
    if target_env not in domains:
        return  # no restriction configured for this env

    allowed_for_env = domains[target_env]
    if not allowed_for_env:
        raise GuardrailViolation(
            f"navigate() blocked: no allowed domains are configured for target_env='{target_env}'"
        )

    host = urlparse(url).hostname or ""
    if not any(host == d or host.endswith(f".{d}") for d in allowed_for_env):
        raise GuardrailViolation(
            f"navigate() blocked: '{host}' is not in the allowed domain list for "
            f"target_env='{target_env}': {allowed_for_env}"
        )


def _check_script_deny_list(script: str) -> None:
    for pattern in HARD_DENY_SCRIPT_PATTERNS:
        if re.search(pattern, script, re.IGNORECASE):
            raise GuardrailViolation(
                f"execute_script() blocked: matched hard-deny pattern '{pattern}'. "
                "Destructive or exfiltration-shaped scripts are never permitted, "
                "regardless of target environment."
            )


PLAUSIBLE_SECRET_PATTERNS = [
    re.compile(r"^\d{16}$"),                 # raw card number
    re.compile(r"^\d{3}-\d{2}-\d{4}$"),       # SSN-shaped
    re.compile(r"sk-[A-Za-z0-9]{20,}"),       # API-key-shaped
]


def _check_no_real_secrets(text: str) -> None:
    """
    Best-effort check that generated tests use obviously-fake fixture data
    (e.g. 'correct-horse-battery-staple', '4111-1111-1111-1111' test card)
    rather than real-looking secrets accidentally hallucinated or pasted by
    a human into a requirement.
    """
    for pattern in PLAUSIBLE_SECRET_PATTERNS:
        if pattern.search(text):
            raise GuardrailViolation(
                "send_keys() blocked: input matches a plausible-real-secret pattern. "
                "Use clearly-fake test fixture data instead."
            )
