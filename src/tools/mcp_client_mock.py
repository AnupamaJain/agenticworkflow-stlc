"""
MockSeleniumBackend — an in-memory, DOM-simulating stand-in for a real
selenium-mcp-server, used so the whole graph (Planner -> Generator -> Guardrail
-> Executor -> Healer -> Reporter) can run end-to-end in a demo/CI environment
with zero external dependencies (no real MCP server, no real browser).

This is intentionally isolated in its own file: swapping to the real
selenium-mcp-server means deleting this file and setting MCP_SDK_AVAILABLE=True
(i.e. `pip install mcp selenium-mcp-server`) — no changes needed anywhere else,
which is the whole point of the MCP boundary (see architecture/03_mcp_integration.md).

It also deliberately simulates ONE realistic failure mode — a stale locator on
the login button (`#submit-btn-old` no longer exists; the real one is
`button[data-testid='submit']`) — so the Self-Healing Agent has something real
to demonstrate in the demo run.
"""
from __future__ import annotations

import time


FAKE_DOM = {
    "https://demo.aiqef.local/login": {
        "title": "AI-QEF Demo Login",
        "elements": {
            ("id", "username"): {"tag": "input", "type": "text"},
            ("id", "password"): {"tag": "input", "type": "password"},
            ("css", "button[data-testid='submit']"): {"tag": "button", "text": "Sign In"},
            ("css", "#submit-btn-old"): None,  # simulates a locator that was removed/renamed
            ("css", ".error-banner"): {"tag": "div", "text": ""},
        },
    }
}


class MockSeleniumBackend:
    _instance: "MockSeleniumBackend | None" = None

    def __init__(self):
        self.current_url: str | None = None
        self.session_values: dict[str, str] = {}
        self.login_attempted = False

    @classmethod
    def instance(cls) -> "MockSeleniumBackend":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def call(self, tool_name: str, args: dict):
        time.sleep(0.05)  # simulate latency for a realistic demo pace
        handler = getattr(self, f"_{tool_name}", None)
        if handler is None:
            raise ValueError(f"MockSeleniumBackend has no handler for tool '{tool_name}'")
        return handler(**args)

    def _navigate(self, url: str, **_):
        self.current_url = url
        if url not in FAKE_DOM:
            raise RuntimeError(f"Mock DOM has no page registered for {url}")
        return {"status": "ok", "title": FAKE_DOM[url]["title"]}

    def _find_element(self, by: str, value: str, **_):
        dom = FAKE_DOM[self.current_url]["elements"]
        key = (by, value)
        el = dom.get(key)
        if el is None:
            raise RuntimeError(f"NoSuchElementException: no element for {by}='{value}'")
        return {"found": True, "tag": el["tag"]}

    def _send_keys(self, by: str, value: str, input_text: str, **_):
        self._find_element(by, value)
        field_name = "username" if value == "username" else "password"
        self.session_values[field_name] = input_text
        return {"status": "ok"}

    def _click(self, by: str, value: str, **_):
        self._find_element(by, value)  # raises if stale locator, e.g. #submit-btn-old
        self.login_attempted = True
        # Simulate the app logic: wrong password -> error banner populated
        if self.session_values.get("password") != "correct-horse-battery-staple":
            FAKE_DOM[self.current_url]["elements"][("css", ".error-banner")]["text"] = (
                "Invalid username or password"
            )
        return {"status": "ok"}

    def _get_text(self, by: str, value: str, **_):
        el = FAKE_DOM[self.current_url]["elements"].get((by, value))
        if el is None:
            raise RuntimeError(f"NoSuchElementException: no element for {by}='{value}'")
        return {"text": el.get("text", "")}

    def _get_page_source(self, **_):
        elements = FAKE_DOM[self.current_url]["elements"]
        lines = ["<html><body>"]
        for (by, value), el in elements.items():
            if el is None:
                continue
            if by == "id":
                lines.append(f'  <{el["tag"]} id="{value}"></{el["tag"]}>')
            elif by == "css" and value.startswith("."):
                lines.append(f'  <{el["tag"]} class="{value[1:]}">{el.get("text","")}</{el["tag"]}>')
            elif by == "css":
                lines.append(f'  <{el["tag"]} data-testid="submit">{el.get("text","")}</{el["tag"]}>')
        lines.append("</body></html>")
        return {"html": "\n".join(lines)}

    def _screenshot(self, path: str, **_):
        return {"status": "ok", "path": path, "note": "mock screenshot (no real image in demo mode)"}

    def _wait_for(self, by: str, value: str, timeout_s: float = 5.0, **_):
        return self._find_element(by, value)

    def _execute_script(self, script: str, **_):
        raise RuntimeError("execute_script is deny-listed by default guardrail config")

    def _write_file(self, path: str, content: str, **_):
        """
        Mock filesystem MCP handler. In offline/demo mode, MCPToolClient never
        actually reaches this — see reporter.py's _write_via_fs_mcp_or_fallback,
        which catches the dispatch failure (since 'filesystem' isn't a real
        connected server in mock mode) and writes directly instead. This
        handler exists so the mock backend has parity with a real
        filesystem-mcp-server if someone wires MCP_SDK_AVAILABLE=True later
        but still wants to unit test against the mock.
        """
        import pathlib
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(path).write_text(content)
        return {"status": "ok", "path": path}
