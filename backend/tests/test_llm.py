"""LLM Provider 测试：FakeProvider 单测 + OpenAICompatProvider mock 测试 + 真机 smoke test.

真机 smoke test 读取旧项目 .env 的 MiMo 凭据（密钥不打印）。
"""
import json
import os
import pytest
from pathlib import Path

from app.llm import ChatMessage, LLMResponse, SchemaValidationError
from app.llm.fake import FakeProvider


# ---------- FakeProvider 测试 ----------

class TestFakeProvider:
    @pytest.mark.asyncio
    async def test_generate_default(self):
        p = FakeProvider()
        resp = await p.generate([ChatMessage(role="user", content="hello")])
        assert resp.text == '{"result": "ok"}'
        assert resp.model == "fake-model"
        assert resp.prompt_tokens == 50
        assert p.call_count == 1

    @pytest.mark.asyncio
    async def test_generate_custom_script(self):
        p = FakeProvider(script={"text": "custom response", "prompt_tokens": 10})
        resp = await p.generate([ChatMessage(role="user", content="test")])
        assert resp.text == "custom response"
        assert resp.prompt_tokens == 10

    @pytest.mark.asyncio
    async def test_generate_json_valid(self):
        p = FakeProvider(script={"text": '{"name": "test", "value": 42}'})
        result = await p.generate_json(
            [ChatMessage(role="user", content="test")],
            schema={"type": "object", "required": ["name", "value"]},
        )
        assert result["name"] == "test"
        assert result["value"] == 42

    @pytest.mark.asyncio
    async def test_generate_json_missing_required(self):
        p = FakeProvider(script={"text": '{"name": "test"}'})
        with pytest.raises(SchemaValidationError, match="missing required fields"):
            await p.generate_json(
                [ChatMessage(role="user", content="test")],
                schema={"type": "object", "required": ["name", "value"]},
            )

    @pytest.mark.asyncio
    async def test_generate_json_invalid_json(self):
        p = FakeProvider(script={"text": "not json"})
        with pytest.raises(SchemaValidationError, match="not valid JSON"):
            await p.generate_json(
                [ChatMessage(role="user", content="test")],
                schema={"type": "object"},
            )

    def test_count_tokens(self):
        p = FakeProvider()
        assert p.count_tokens("hello world") == 2
        assert p.count_tokens("hello   world   test") == 3


# ---------- OpenAICompatProvider mock 测试 ----------

import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from app.llm.openai_compat import OpenAICompatProvider


class TestOpenAICompatProvider:
    @pytest.mark.asyncio
    async def test_generate_success(self):
        """Mock httpx client to verify request construction."""
        provider = OpenAICompatProvider(
            base_url="https://test.api.com/v1",
            api_key="test-key",
            model="test-model",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Hello from LLM"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "test-model",
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False
        provider._client = mock_client

        resp = await provider.generate([ChatMessage(role="user", content="hello")])
        assert resp.text == "Hello from LLM"
        assert resp.prompt_tokens == 10
        assert resp.completion_tokens == 5
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/chat/completions"
        assert call_args[1]["json"]["model"] == "test-model"
        await provider.close()

    def test_count_tokens_chinese(self):
        provider = OpenAICompatProvider(base_url="https://test", api_key="k")
        count = provider.count_tokens("你好世界")
        assert count > 0
        assert count == 6  # 4 chars * 1.5

    def test_count_tokens_english(self):
        provider = OpenAICompatProvider(base_url="https://test", api_key="k")
        count = provider.count_tokens("hello world test")
        assert count > 0


# ---------- 真机 smoke test（MiMo） ----------

OLD_PROJECT_ENV = Path("/home/xinlei/桌面/deepseek harness/ai-learning-assistant/.env")


def _load_mimo_credentials() -> tuple[str, str, str] | None:
    """从旧项目 .env 读取 MiMo 凭据（不打印密钥值）。"""
    if not OLD_PROJECT_ENV.exists():
        return None
    creds = {}
    for line in OLD_PROJECT_ENV.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            creds[k.strip()] = v.strip()
    base_url = creds.get("AI_BASE_URL", "")
    api_key = creds.get("AI_API_KEY", "")
    model = creds.get("AI_CHAT_MODEL", "")
    if not all([base_url, api_key, model]):
        return None
    return base_url, api_key, model


@pytest.mark.asyncio
@pytest.mark.skipif(not OLD_PROJECT_ENV.exists(), reason="旧项目 .env 不存在")
async def test_mimo_smoke():
    """真机 smoke test：调用 MiMo API，验证连接与响应格式。
    
    此测试使用真实 API key，只验证基本连通性，不测试具体推理能力。
    """
    creds = _load_mimo_credentials()
    if not creds:
        pytest.skip("无法读取 MiMo 凭据")
    base_url, api_key, model = creds

    provider = OpenAICompatProvider(base_url=base_url, api_key=api_key, model=model, timeout=30.0)
    try:
        resp = await provider.generate(
            messages=[ChatMessage(role="user", content="请用一句话回答：1+1等于几？")],
            max_tokens=200,
        )
        # MiMo 是推理模型：thinking 在 reasoning_content，answer 在 content
        # 若 content 为空，检查 reasoning_content 是否有值
        has_content = bool(resp.text)
        has_reasoning = bool((resp.raw or {}).get("choices", [{}])[0].get("message", {}).get("reasoning_content"))
        assert has_content or has_reasoning, "LLM 响应不能为空（content 或 reasoning_content 至少一个有值）"
        assert resp.model, "model 字段不能为空"
        assert resp.prompt_tokens > 0 or resp.completion_tokens > 0, "token 统计应有数据"
        # 验证 count_tokens 不崩溃
        tokens = provider.count_tokens(resp.text)
        assert tokens >= 0
    finally:
        await provider.close()