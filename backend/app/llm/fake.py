"""FakeProvider (test-only): scripted responses, no external API calls.

Guarantees deterministic behavior for tests.
Never imported in production code paths.
"""
from __future__ import annotations
import json, re
from typing import Any

from app.llm import (
    ChatMessage, LLMProvider, LLMResponse, SchemaValidationError,
)


class FakeProvider(LLMProvider):
    def __init__(self, script: dict[str, Any] | None = None) -> None:
        self._script = script or {}
        self.call_count = 0
        self.last_messages: list[ChatMessage] = []

    async def generate(self, messages: list[ChatMessage], *, model: str | None = None,
                       temperature: float | None = None, max_tokens: int | None = None,
                       timeout: float | None = None) -> LLMResponse:
        self.call_count += 1
        self.last_messages = list(messages)
        return LLMResponse(
            text=self._script.get("text", '{"result": "ok"}'),
            model=model or "fake-model",
            prompt_tokens=self._script.get("prompt_tokens", 50),
            completion_tokens=self._script.get("completion_tokens", 30),
            total_tokens=self._script.get("total_tokens", 80),
            finish_reason="stop",
        )

    async def generate_json(self, messages: list[ChatMessage], schema: dict[str, Any], *,
                            model: str | None = None, temperature: float | None = None,
                            max_tokens: int | None = None, timeout: float | None = None) -> dict[str, Any]:
        text = self._script.get("text", '{"result": "ok"}')
        try:
            result = json.loads(text)
        except json.JSONDecodeError as e:
            raise SchemaValidationError(f"FakeProvider script not valid JSON: {e}")
        required = schema.get("required", [])
        if required and isinstance(result, dict):
            missing = [k for k in required if k not in result]
            if missing:
                raise SchemaValidationError(f"FakeProvider JSON missing required fields: {missing}")
        return result

    def count_tokens(self, text: str) -> int:
        return len(re.findall(r"\S+", text))