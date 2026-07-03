"""
RealLLMClient — drop-in replacement for FakeLLMClient that calls the actual
Anthropic API. Same `.complete(messages) -> str` interface, so swapping it in
graph.py (`llm_client = RealLLMClient()` instead of `FakeLLMClient()`) requires
zero changes to any agent code.

Requires: pip install anthropic
Requires: ANTHROPIC_API_KEY environment variable set.
"""
from __future__ import annotations

import os


class RealLLMClient:
    def __init__(self, model: str = "claude-sonnet-4-6", max_tokens: int = 2000):
        import anthropic  # deferred import so the demo doesn't require this package

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Export it, or use FakeLLMClient for the "
                "offline demo (see langgraph_agent/graph.py's run_demo())."
            )
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    async def complete(self, messages: list[dict]) -> str:
        system = messages[0]["content"] if messages and messages[0]["role"] == "system" else None
        user_messages = [m for m in messages if m["role"] != "system"]

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=user_messages,
        )
        return "".join(block.text for block in response.content if block.type == "text")
