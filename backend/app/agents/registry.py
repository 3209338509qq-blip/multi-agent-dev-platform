"""全局 Agent 注册表单例。

Phase 2 测试通过 set_registry() 注入 ScriptedAgent；
Phase 4-7 逐步注册真实 Agent 实现。
"""
from __future__ import annotations
from app.agents import BaseAgent
from app.orchestrator.orchestrator import AgentRegistry

_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry


def set_registry(registry: AgentRegistry) -> None:
    global _registry
    _registry = registry
