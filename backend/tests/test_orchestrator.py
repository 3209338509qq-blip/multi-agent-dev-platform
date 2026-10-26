"""Orchestrator 集成测试：真实 DB + ScriptedAgent，验证完整调度闭环。"""
import asyncio
import pytest
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import ScriptedAgent
from app.agents.registry import get_registry, set_registry
from app.config import Settings, get_settings
import app.database as db_mod
from app.models import (
    AgentRole, Base, Project, ProjectStatus, Task, TaskDependency, TaskStatus,
)
from app.orchestrator import Orchestrator, AgentRegistry
from app.services.event_bus import EventBus
from app.services.memory import MemoryService


@pytest.fixture
async def setup_db(tmp_path, monkeypatch):
    """每个测试用独立临时 DB，monkeypatch 确保所有模块看到同一引擎。"""
    db_url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    ws_root = str(tmp_path / "workspace")
    Path(ws_root).mkdir(parents=True, exist_ok=True)

    new_engine = db_mod.create_async_engine(db_url, echo=False)
    new_factory = db_mod.async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_mod, "engine", new_engine)
    monkeypatch.setattr(db_mod, "async_session_factory", new_factory)

    async with new_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = Settings(
        _env_file=None,
        database_url=db_url,
        workspace_root=ws_root,
        max_parallel_tasks=2,
        agent_timeout_seconds=30,
        task_max_retries=2,
    )
    event_bus = EventBus()
    memory = MemoryService(ws_root)
    return {"settings": settings, "event_bus": event_bus, "memory": memory, "ws_root": ws_root, "tmp_path": tmp_path}


async def _create_project_with_tasks(tmp_path: Path, tasks_def: list[dict], ws_root: str) -> str:
    async with db_mod.async_session_factory() as db:
        project = Project(
            id="test-proj-001",
            name="Test Project",
            requirement="test requirement",
            status=ProjectStatus.PLANNING,
            workspace_path=str(Path(ws_root) / "projects" / "test-proj-001"),
            config={},
        )
        db.add(project)
        for td in tasks_def:
            task = Task(
                id=td["id"],
                project_id="test-proj-001",
                agent_role=AgentRole(td["role"]),
                title=td["title"],
                status=TaskStatus.PENDING,
                max_retries=td.get("max_retries", 2),
                input_data=td.get("input_data"),
            )
            db.add(task)
        await db.flush()
        for td in tasks_def:
            for dep_id in td.get("deps", []):
                db.add(TaskDependency(task_id=td["id"], depends_on_id=dep_id))
        await db.commit()
    Path(ws_root) / "projects" / "test-proj-001" / ".agent"
    (Path(ws_root) / "projects" / "test-proj-001" / ".agent").mkdir(parents=True, exist_ok=True)
    return "test-proj-001"


@pytest.mark.asyncio
async def test_linear_dag_success(setup_db):
    """PM → Architect → Backend → Git，全部 SUCCESS。"""
    ctx = setup_db
    tasks_def = [
        {"id": "t-pm", "role": "pm", "title": "需求分析"},
        {"id": "t-arch", "role": "architect", "title": "架构设计", "deps": ["t-pm"]},
        {"id": "t-be", "role": "backend", "title": "后端开发", "deps": ["t-arch"]},
        {"id": "t-git", "role": "git", "title": "Git 提交", "deps": ["t-be"]},
    ]
    project_id = await _create_project_with_tasks(ctx["tmp_path"], tasks_def, ctx["ws_root"])

    registry = AgentRegistry()
    for role in ["pm", "architect", "backend", "git"]:
        registry.register(ScriptedAgent(AgentRole(role)))

    orch = Orchestrator(project_id, registry, ctx["event_bus"], ctx["memory"], ctx["settings"])
    result = await orch.run()

    assert result == ProjectStatus.COMPLETED
    async with db_mod.async_session_factory() as db:
        from sqlalchemy import select
        res = await db.execute(select(Task).where(Task.project_id == project_id))
        tasks = list(res.scalars().all())
        for t in tasks:
            assert t.status == TaskStatus.SUCCESS, f"Task {t.id} expected SUCCESS, got {t.status.value}"


@pytest.mark.asyncio
async def test_parallel_tasks(setup_db):
    """Architect → (Backend + Frontend) 并行 → Git。"""
    ctx = setup_db
    tasks_def = [
        {"id": "t-arch", "role": "architect", "title": "架构设计"},
        {"id": "t-be", "role": "backend", "title": "后端开发", "deps": ["t-arch"]},
        {"id": "t-fe", "role": "frontend", "title": "前端开发", "deps": ["t-arch"]},
        {"id": "t-git", "role": "git", "title": "Git 提交", "deps": ["t-be", "t-fe"]},
    ]
    project_id = await _create_project_with_tasks(ctx["tmp_path"], tasks_def, ctx["ws_root"])

    registry = AgentRegistry()
    for role in ["architect", "backend", "frontend", "git"]:
        registry.register(ScriptedAgent(AgentRole(role)))

    orch = Orchestrator(project_id, registry, ctx["event_bus"], ctx["memory"], ctx["settings"])
    result = await orch.run()
    assert result == ProjectStatus.COMPLETED


@pytest.mark.asyncio
async def test_retry_then_success(setup_db):
    """任务首次失败，重试成功。"""
    ctx = setup_db
    tasks_def = [{"id": "t-1", "role": "pm", "title": "任务1", "max_retries": 2}]
    project_id = await _create_project_with_tasks(ctx["tmp_path"], tasks_def, ctx["ws_root"])

    class FailThenOkAgent(ScriptedAgent):
        def __init__(self):
            super().__init__(AgentRole.PM)
            self._fail_count = 0
        async def run(self, ctx_agent):
            self.run_count += 1
            if self._fail_count < 1:
                self._fail_count += 1
                return await super().run(ctx_agent)
            self._script = {"behavior": "success"}
            return await super().run(ctx_agent)

    registry = AgentRegistry()
    agent = FailThenOkAgent()
    agent._script = {"behavior": "fail", "error": "first attempt"}
    registry.register(agent)

    orch = Orchestrator(project_id, registry, ctx["event_bus"], ctx["memory"], ctx["settings"])
    result = await orch.run()

    assert result == ProjectStatus.COMPLETED
    async with db_mod.async_session_factory() as db:
        task = await db.get(Task, "t-1")
        assert task.status == TaskStatus.SUCCESS
        assert task.retry_count >= 1


@pytest.mark.asyncio
async def test_cascade_block_on_failure(setup_db):
    """PM 最终失败 → 下游 BLOCKED → 项目 FAILED。"""
    ctx = setup_db
    tasks_def = [
        {"id": "t-pm", "role": "pm", "title": "PM", "max_retries": 0},
        {"id": "t-arch", "role": "architect", "title": "Arch", "deps": ["t-pm"]},
        {"id": "t-be", "role": "backend", "title": "BE", "deps": ["t-arch"]},
    ]
    project_id = await _create_project_with_tasks(ctx["tmp_path"], tasks_def, ctx["ws_root"])

    registry = AgentRegistry()
    registry.register(ScriptedAgent(AgentRole.PM, {"behavior": "fail", "error": "permanent failure"}))
    registry.register(ScriptedAgent(AgentRole.ARCHITECT))
    registry.register(ScriptedAgent(AgentRole.BACKEND))

    orch = Orchestrator(project_id, registry, ctx["event_bus"], ctx["memory"], ctx["settings"])
    result = await orch.run()

    assert result == ProjectStatus.FAILED
    async with db_mod.async_session_factory() as db:
        pm = await db.get(Task, "t-pm")
        arch = await db.get(Task, "t-arch")
        be = await db.get(Task, "t-be")
        assert pm.status == TaskStatus.FAILED
        assert arch.status == TaskStatus.BLOCKED
        assert be.status == TaskStatus.BLOCKED


@pytest.mark.asyncio
async def test_events_emitted(setup_db):
    """验证事件序列。"""
    ctx = setup_db
    tasks_def = [{"id": "t-1", "role": "pm", "title": "PM"}]
    project_id = await _create_project_with_tasks(ctx["tmp_path"], tasks_def, ctx["ws_root"])

    registry = AgentRegistry()
    registry.register(ScriptedAgent(AgentRole.PM))

    orch = Orchestrator(project_id, registry, ctx["event_bus"], ctx["memory"], ctx["settings"])
    await orch.run()

    events = ctx["event_bus"].get_project_events(project_id)
    types = [e.type for e in events]
    assert "project_started" in types
    assert "agent_started" in types
    assert "agent_completed" in types
    assert "task_completed" in types
    assert "project_completed" in types


async def test_upstream_artifacts_reach_developers(setup_db):
    """依赖顺序之外，实际的架构 JSON 也必须送到开发 Agent。"""
    ctx = setup_db
    project_id = await _create_project_with_tasks(ctx["tmp_path"], [
        {"id": "arch", "role": "architect", "title": "架构"},
        {"id": "backend", "role": "backend", "title": "后端", "deps": ["arch"]},
        {"id": "frontend", "role": "frontend", "title": "前端", "deps": ["arch"]},
    ], ctx["ws_root"])
    architecture = {"api_design": [{"path": "/members", "method": "GET"}],
                    "database_schema": [{"table": "members"}]}
    registry = AgentRegistry()
    registry.register(ScriptedAgent(AgentRole.ARCHITECT, {"output": architecture}))
    received = {}

    class CaptureAgent(ScriptedAgent):
        async def run(self, agent_ctx):
            received[self.role] = agent_ctx.input_data
            # 前端看到的 running 状态必须来自数据库，而不只是内存调度器。
            async with db_mod.async_session_factory() as db:
                task = await db.get(Task, agent_ctx.task_id)
                assert task.status == TaskStatus.RUNNING
                assert task.started_at is not None
            return await super().run(agent_ctx)

    for role in (AgentRole.BACKEND, AgentRole.FRONTEND):
        registry.register(CaptureAgent(role))
    orch = Orchestrator(project_id, registry, ctx["event_bus"], ctx["memory"], ctx["settings"])
    assert await orch.run() == ProjectStatus.COMPLETED
    for role in (AgentRole.BACKEND, AgentRole.FRONTEND):
        assert received[role]["api_design"] == architecture["api_design"]
        assert received[role]["database_schema"] == architecture["database_schema"]
        assert received[role]["requirement"] == "test requirement"
        assert received[role]["upstream_outputs"]["arch"]["output_data"] == architecture


async def test_invalid_persisted_graph_fails_promptly(setup_db):
    ctx = setup_db
    project_id = await _create_project_with_tasks(ctx["tmp_path"], [
        {"id": "a", "role": "backend", "title": "A", "deps": ["b"]},
        {"id": "b", "role": "frontend", "title": "B", "deps": ["a"]},
    ], ctx["ws_root"])
    orch = Orchestrator(project_id, AgentRegistry(), ctx["event_bus"], ctx["memory"], ctx["settings"])
    assert await asyncio.wait_for(orch.run(), timeout=2) == ProjectStatus.FAILED
    async with db_mod.async_session_factory() as db:
        assert (await db.get(Project, project_id)).status == ProjectStatus.FAILED


async def test_timeout_is_not_overwritten_as_completed(setup_db):
    ctx = setup_db
    ctx["settings"].agent_timeout_seconds = 0.02
    project_id = await _create_project_with_tasks(ctx["tmp_path"], [
        {"id": "slow", "role": "backend", "title": "Slow", "max_retries": 0},
    ], ctx["ws_root"])
    registry = AgentRegistry()
    registry.register(ScriptedAgent(AgentRole.BACKEND, {"delay": 1}))
    orch = Orchestrator(project_id, registry, ctx["event_bus"], ctx["memory"], ctx["settings"])
    assert await orch.run() == ProjectStatus.FAILED
    async with db_mod.async_session_factory() as db:
        assert (await db.get(Project, project_id)).status == ProjectStatus.FAILED
