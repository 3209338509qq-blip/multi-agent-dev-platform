"""OpenAI Compatible Provider (httpx direct).

Covers: DeepSeek / MiMo / Qwen / OpenAI / SiliconFlow /chat/completions.
"""
from __future__ import annotations
import json, logging, re, time
from typing import Any

import httpx
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_sleep_log,
)

from app.llm import (
    ChatMessage, LLMProvider, LLMResponse, SchemaValidationError,
)

logger = logging.getLogger("madp.llm.openai_compat")


class OpenAICompatProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: str, model: str = "deepseek-chat",
                 timeout: float = 120.0, max_retries: int = 3) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                timeout=httpx.Timeout(self._timeout),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ReadTimeout, httpx.ConnectTimeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def generate(self, messages: list[ChatMessage], *, model: str | None = None,
                       temperature: float | None = None, max_tokens: int | None = None,
                       timeout: float | None = None) -> LLMResponse:
        client = await self._get_client()
        payload: dict[str, Any] = {
            "model": model or self._model,
            "messages": [m.to_openai() for m in messages],
            "temperature": temperature if temperature is not None else 0.2,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        req_timeout = timeout or self._timeout
        t0 = time.monotonic()
        resp = await client.post("/chat/completions", json=payload, timeout=httpx.Timeout(req_timeout))
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        if resp.status_code >= 400:
            raise httpx.HTTPStatusError(f"LLM API error {resp.status_code}: {resp.text}", request=resp.request, response=resp)
        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        usage = data.get("usage", {})
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.info("LLM %s: %dms, prompt=%d, completion=%d", payload["model"], duration_ms, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        # MiMo 等推理模型：thinking 在 reasoning_content，answer 在 content
        # 当 content 为空时保留空字符串（不 fallback 到 reasoning），由调用方决定
        return LLMResponse(
            text=msg.get("content") or "", model=data.get("model", payload["model"]),
            prompt_tokens=usage.get("prompt_tokens", 0), completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0), finish_reason=choice.get("finish_reason"), raw=data,
        )

    async def generate_json(self, messages: list[ChatMessage], schema: dict[str, Any], *,
                            model: str | None = None, temperature: float | None = None,
                            max_tokens: int | None = None, timeout: float | None = None) -> dict[str, Any]:
        schema_hint = json.dumps(schema, ensure_ascii=False, indent=2)
        enhanced = list(messages)
        instruction = "\n\nPlease output valid JSON matching this schema (nothing else):\n" + schema_hint
        if enhanced and enhanced[0].role == "system":
            enhanced[0] = ChatMessage(role="system", content=enhanced[0].content + instruction)
        else:
            enhanced.insert(0, ChatMessage(role="system", content=instruction.lstrip()))
        resp = await self.generate(enhanced, model=model, temperature=temperature if temperature is not None else 0.1, max_tokens=max_tokens, timeout=timeout)
        text = resp.text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            text = text.strip()
        try:
            result = json.loads(text)
        except json.JSONDecodeError as e:
            raise SchemaValidationError(f"LLM output is not valid JSON: {e}\nRaw: {text[:500]}")
        required = schema.get("required", [])
        if required and isinstance(result, dict):
            missing = [k for k in required if k not in result]
            if missing:
                raise SchemaValidationError(f"JSON missing required fields: {missing}")
        return result

    def count_tokens(self, text: str) -> int:
        """Crude token estimate (budget control, +/-20% tolerance)."""
        cn = len(re.findall(r"[\u4e00-\u9fff]", text))
        en = len(re.findall(r"[a-zA-Z]+", text))
        other = len(text) - cn - sum(len(w) for w in re.findall(r"[a-zA-Z]+", text))
        return int(cn * 1.5 + en * 1.3 + other * 0.5)