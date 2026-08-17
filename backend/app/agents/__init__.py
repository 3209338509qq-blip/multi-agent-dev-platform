"""Agent 基类与上下文/结果契约。

所有 8 个专职 Agent（PM/Architect/Backend/Frontend/Test/Review/Debug/Git）
均继承 BaseAgent，接口统一：run(ctx) -> AgentResult。
Phase 4-7 逐个实现；Phase 2 测试用 ScriptedAgent。
"""
from __future__ import annotations
import abc
from dataclasses import dataclass, field
from typing import Any

from app.models import AgentRole, TaskStatus


@dataclass
class AgentContext:
    """执行上下文：Agent 运行所需的一切信息（不依赖聊天上下文）。"""
    task_id: str
    project_id: str
    agent_role: AgentRole
    title: str
    description: str
    input_data: dict[str, Any] | None = None
    workspace_path: str = ""
    project_memory: dict[str, Any] = field(default_factory=dict)
    agent_memory: list[dict[str, Any]] = field(default_factory=list)
    task_memory: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Agent 执行结果。status 必须为 SUCCESS/FAILED/BLOCKED 之一。"""
    status: TaskStatus
    output_data: dict[str, Any] | None = None
    error: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0
    model: str | None = None


class BaseAgent(abc.ABC):
    """Agent 抽象基类。"""
    role: AgentRole

    @abc.abstractmethod
    async def run(self, ctx: AgentContext) -> AgentResult:
        ...


class ScriptedAgent(BaseAgent):
    """脚本化 Agent（仅测试用）：按预设脚本返回结果，不调用 LLM。"""
    def __init__(self, role: AgentRole, script: dict[str, Any] | None = None) -> None:
        self.role = role
        self._script = script or {}
        self.run_count = 0

    async def run(self, ctx: AgentContext) -> AgentResult:
        self.run_count += 1
        behavior = self._script.get("behavior", "success")
        delay = self._script.get("delay", 0.0)
        if delay > 0:
            import asyncio
            await asyncio.sleep(delay)
        if behavior == "fail":
            return AgentResult(
                status=TaskStatus.FAILED,
                error=self._script.get("error", "scripted failure"),
                prompt_tokens=10, completion_tokens=5,
            )
        elif behavior == "timeout":
            import asyncio
            await asyncio.sleep(9999)
            return AgentResult(status=TaskStatus.FAILED, error="unexpected")
        return AgentResult(
            status=TaskStatus.SUCCESS,
            output_data=self._script.get("output", {"result": "ok", "role": ctx.agent_role.value}),
            prompt_tokens=self._script.get("prompt_tokens", 50),
            completion_tokens=self._script.get("completion_tokens", 30),
        )
