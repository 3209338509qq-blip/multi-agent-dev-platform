"""健康检查与配置加载的冒烟测试。"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "multi-agent-dev-platform"
    assert body["version"]


def test_settings_defaults():
    """默认配置必须可用（无 .env 时也能启动，保证本地零配置跑通）。"""
    s = Settings(_env_file=None)
    assert s.llm_provider == "openai_compatible"
    assert s.task_max_retries == 2
    assert s.debug_max_rounds == 3
    assert s.sandbox_backend in {"local", "docker"}
    assert s.database_url.startswith("sqlite+")


def test_settings_cached_singleton():
    assert get_settings() is get_settings()
