"""全局 Agent 注册表单例。

create_default_registry() 注册全部 8 个 Agent（使用配置的 LLM Provider）。
测试通过 set_registry() 注入 ScriptedAgent 覆盖。
"""
from __future__ import annotations
from app.agents import BaseAgent
from app.orchestrator.orchestrator import AgentRegistry
from app.models import AgentRole

_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = create_default_registry()
    return _registry


def set_registry(registry: AgentRegistry) -> None:
    global _registry
    _registry = registry


def create_default_registry() -> AgentRegistry:
    """创建包含全部 8 个 Agent 的注册表（使用配置的 LLM Provider）。"""
    from app.config import get_settings
    from app.llm.openai_compat import OpenAICompatProvider
    from app.agents.pm import PMAgent
    from app.agents.architect import ArchitectAgent
    from app.agents.backend import BackendAgent
    from app.agents.frontend import FrontendAgent
    from app.agents.test_agent import TestAgent
    from app.agents.review import ReviewAgent
    from app.agents.debug import DebugAgent
    from app.agents.git import GitAgent

    settings = get_settings()

    # 创建 LLM Provider
    llm = OpenAICompatProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )

    registry = AgentRegistry()
    registry.register(PMAgent(llm))
    registry.register(ArchitectAgent(llm))
    registry.register(BackendAgent(llm))
    registry.register(FrontendAgent(llm))
    registry.register(TestAgent())
    registry.register(ReviewAgent(llm))
    registry.register(DebugAgent(llm))
    registry.register(GitAgent())

    return registry
