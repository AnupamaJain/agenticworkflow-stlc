"""
Unit tests for the deterministic guardrail layer (guardrails/mcp_guardrails.py).
Run: pytest tests/test_guardrails.py -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from guardrails.mcp_guardrails import GuardrailViolation, check_tool_call


CONFIG = {
    "guardrails": {
        "allowed_tools": ["navigate", "click", "send_keys", "get_text"],
        "allowed_domains": {"sandbox": ["demo.aiqef.local", "localhost"], "production": []},
        "max_tool_calls_per_test": 40,
    }
}


def test_allowed_tool_passes():
    check_tool_call("click", {"by": "css", "value": "#btn"}, "sandbox", CONFIG)  # should not raise


def test_disallowed_tool_blocked():
    with pytest.raises(GuardrailViolation, match="not on the guardrail allow-list"):
        check_tool_call("execute_script", {"script": "alert(1)"}, "sandbox", CONFIG)


def test_sandbox_domain_allowed():
    check_tool_call("navigate", {"url": "https://demo.aiqef.local/login"}, "sandbox", CONFIG)


def test_off_domain_navigate_blocked():
    with pytest.raises(GuardrailViolation, match="not in the allowed domain list"):
        check_tool_call("navigate", {"url": "https://evil.com/phish"}, "sandbox", CONFIG)


def test_production_domain_empty_blocks_everything():
    with pytest.raises(GuardrailViolation):
        check_tool_call("navigate", {"url": "https://yourapp.com"}, "production", CONFIG)


@pytest.mark.parametrize("script", [
    "localStorage.clear()",
    "document.cookie = 'x=1'",
    "fetch('/api/users', {method: 'DELETE'})",
    "DROP TABLE users;",
])
def test_destructive_scripts_blocked(script):
    config = {**CONFIG, "guardrails": {**CONFIG["guardrails"], "allowed_tools": [*CONFIG["guardrails"]["allowed_tools"], "execute_script"]}}
    with pytest.raises(GuardrailViolation, match="hard-deny pattern"):
        check_tool_call("execute_script", {"script": script}, "sandbox", config)


@pytest.mark.parametrize("secret", ["4111111111111111", "123-45-6789", "sk-abcdefghijklmnopqrstuvwx"])
def test_plausible_secrets_blocked(secret):
    with pytest.raises(GuardrailViolation, match="plausible-real-secret"):
        check_tool_call("send_keys", {"by": "id", "value": "password", "input_text": secret}, "sandbox", CONFIG)


def test_fake_fixture_password_allowed():
    check_tool_call(
        "send_keys", {"by": "id", "value": "password", "input_text": "wrong-password-123"}, "sandbox", CONFIG
    )
