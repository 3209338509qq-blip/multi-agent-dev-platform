"""LLM Provider 抽象层。

统一接口覆盖 DeepSeek / MiMo / Qwen / OpenAI / Claude（Anthropic）。
配置通过 .env 的 LLM_PROVIDER / LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 控制。
FakeProvider 仅用于单元测试，生产路径不引用。
"""
from __future__ import annotations
import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LLMProviderType(str, Enum):
    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC = "anthropic"
    FAKE = "fake"


@dataclass
class ChatMessage:
    """统一消息格式（OpenAI / Anthropic 均可映射）。"""
    role: str          # "system" | "user" | "assistant"
    content: str

    def to_openai(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}

    def to_anthropic(self) -> dict[str, str]:
        # Anthropic 的 system 通过顶层参数传入，此处只映射 user/assistant
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    """LLM 响应的统一数据结构。"""
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str | None = None
    raw: dict[str, Any] | None = None  # 原始 API 响应（调试用）


@dataclass
class LLMUsage:
    """Token 用量统计。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class SchemaValidationError(Exception):
    """LLM 输出不符合预期 JSON Schema 时抛出。"""
    pass


class LLMProvider(abc.ABC):
    """LLM Provider 抽象基类。

    所有实现必须遵循：
    - generate(): 文本生成（返回 LLMResponse）
    - generate_json(): JSON 生成 + schema 校验（失败抛 SchemaValidationError）
    - count_tokens(): token 估算（用于预算控制）
    """

    @abc.abstractmethod
    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> LLMResponse:
        ...

    @abc.abstractmethod
    async def generate_json(
        self,
        messages: list[ChatMessage],
        schema: dict[str, Any],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        ...

    @abc.abstractmethod
    def count_tokens(self, text: str) -> int:
        """估算文本 token 数（用于预算控制，允许 ±20% 误差）。"""
        ...
