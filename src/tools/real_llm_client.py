"""
RealLLMClient — A unified LLM Gateway Client that routes queries dynamically
to Groq, Google Gemini, or Anthropic depending on which API key is present
in the environment. Same .complete(messages) -> str interface.
"""
from __future__ import annotations

import os


class RealLLMClient:
    def __init__(self, provider: str | None = None, model: str | None = None, max_tokens: int = 2000):
        # 1. Detect API keys
        self.groq_key = os.environ.get("GROQ_API_KEY")
        self.gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

        # 2. Set provider
        if provider:
            self.provider = provider.lower()
        elif self.groq_key:
            self.provider = "groq"
        elif self.gemini_key:
            self.provider = "google"
        elif self.anthropic_key:
            self.provider = "anthropic"
        else:
            raise RuntimeError(
                "No API Key found. Please set GROQ_API_KEY, GEMINI_API_KEY (or GOOGLE_API_KEY), "
                "or ANTHROPIC_API_KEY in your environment variables."
            )

        # 3. Determine default model based on provider
        if model:
            self.model = model
        else:
            if self.provider == "groq":
                self.model = "llama-3.3-70b-versatile"
            elif self.provider == "google":
                self.model = "gemini-1.5-pro"
            else:
                self.model = "claude-3-5-sonnet-latest"

        self.max_tokens = max_tokens

    async def complete(self, messages: list[dict]) -> str:
        import httpx

        async with httpx.AsyncClient(timeout=60.0) as client:
            # GROQ PROVIDER
            if self.provider == "groq":
                if not self.groq_key:
                    raise RuntimeError("GROQ_API_KEY environment variable is not set.")
                
                url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {self.groq_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": self.max_tokens,
                    "temperature": 0.0
                }
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]

            # GOOGLE GEMINI PROVIDER
            elif self.provider == "google":
                if not self.gemini_key:
                    raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable is not set.")
                
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.gemini_key}"
                headers = {
                    "Content-Type": "application/json"
                }
                
                contents = []
                system_instruction = None
                for msg in messages:
                    role = msg["role"]
                    content = msg["content"]
                    if role == "system":
                        system_instruction = {
                            "parts": [{"text": content}]
                        }
                    else:
                        gemini_role = "model" if role in ("assistant", "model") else "user"
                        contents.append({
                            "role": gemini_role,
                            "parts": [{"text": content}]
                        })
                
                payload = {
                    "contents": contents,
                    "generationConfig": {
                        "maxOutputTokens": self.max_tokens,
                        "temperature": 0.0
                    }
                }
                if system_instruction:
                    payload["systemInstruction"] = system_instruction
                    
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError) as e:
                    raise RuntimeError(f"Error parsing Gemini response: {response.text}") from e

            # ANTHROPIC PROVIDER
            elif self.provider == "anthropic":
                if not self.anthropic_key:
                    raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set.")
                
                url = "https://api.anthropic.com/v1/messages"
                headers = {
                    "x-api-key": self.anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
                
                system = messages[0]["content"] if messages and messages[0]["role"] == "system" else None
                user_messages = [m for m in messages if m["role"] != "system"]
                
                payload = {
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "messages": user_messages
                }
                if system:
                    payload["system"] = system
                    
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return "".join(block["text"] for block in data["content"] if block["type"] == "text")

            else:
                raise ValueError(f"Unknown provider: {self.provider}")
