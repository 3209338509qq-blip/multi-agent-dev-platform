"""PM Agent 集成测试：PM 输出 → 动态任务创建 → 编排器全流程。

测试场景：
1. PM 生成结构化 JSON → 自动创建 architect/backend/frontend/test/review/git 任务
2. 编排器重建调度器 → 并行执行 backend+frontend → 全部 SUCCESS
3. PM 生成无效输出 → FAILED
"""
import asyncio
import json
import pytest
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import AgentContext, AgentResult, ScriptedAgent
from app.agents.registry import set_registry
from app.agents.pm import PMAgent
from app.config import Settings
import app.database as db_mod
from app.llm.fake import FakeProvider
from app.models import AgentRole, Base, Project, ProjectStatus, Task, TaskStatus
from app.orchestrator import Orchestrator, AgentRegistry
from app.services.event_bus import EventBus
from app.services.memory import MemoryService


PM_OUTPUT = {
    "project_name": "班费管理系统",
    "description": "大学生班费收支管理",
    "requirements": [
        {"id": "FR-1", "type": "functional", "description": "班级成员管理", "priority": "high"},
        {"id": "FR-2", "type": "functional", "description": "收入支出记录", "priority": "high"},
        {"id": "FR-3", "type": "functional", "description": "余额统计", "priority": "high"},
        {"id": "NFR-1", "type": "non_functional", "description": "响应式UI", "priority": "medium"},
    ],
    "acceptance_criteria": ["能添加成员", "能记账", "能查余额"],
    "tasks": [
        {"role": "architect", "title": "架构设计", "description": "设计系统架构", "depends_on": []},
        {"role": "backend", "title": "后端开发", "description": "FastAPI API", "depends_on": ["architect"]},
        {"role": "frontend", "title": "前端开发", "description": "HTML UI", "depends_on": ["architect"]},
        {"role": "test", "title": "测试", "description": "pytest 测试", "depends_on": ["backend", "frontend"]},
        {"role": "review", "title": "代码审查", "description": "审查代码", "depends_on": ["test"]},
        {"role": "git", "title": "Git提交", "description": "提交代码", "depends_on": ["review"]},
    ],
}


@pytest.fixture
async def setup_env(tmp_path, monkeypatch):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/pm_test.db"
    ws_root = str(tmp_path / "workspace")
    Path(ws_root).mkdir(parents=True, exist_ok=True)
    new_engine = db_mod.create_async_engine(db_url, echo=False)
    new_factory = db_mod.async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_mod, "engine", new_engine)
    monkeypatch.setattr(db_mod, "async_session_factory", new_factory)
    async with new_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = Settings(
        _env_file=None, database_url=db_url, workspace_root=ws_root,
        max_parallel_tasks=3, agent_timeout_seconds=30, task_max_retries=1,
    )
    return {"settings": settings, "ws_root": ws_root, "tmp_path": tmp_path}


async def _create_project_with_pm(tmp_path, ws_root):
    project_id = "pm-test-001"
    async with db_mod.async_session_factory() as db:
        db.add(Project(
            id=project_id, name="Test", requirement="班费管理系统",
            status=ProjectStatus.PLANNING,
            workspace_path=str(Path(ws_root) / "projects" / project_id),
        ))
        db.add(Task(
            id=f"{project_id}-pm-0", project_id=project_id,
            agent_role=AgentRole.PM, title="需求分析",
            status=TaskStatus.PENDING,
            input_data={"requirement": "创建一个大学生班费管理系统，需要支持班级成员、收入、支出、余额统计、账单查询。"},
        ))
        await db.commit()
    (Path(ws_root) / "projects" / project_id / ".agent").mkdir(parents=True, exist_ok=True)
    return project_id


@pytest.mark.asyncio
async def test_pm_creates_downstream_tasks(setup_env):
    """PM 输出有效 JSON → 自动创建 6 个后续任务 → 全部 SUCCESS。"""
    ctx = setup_env
    project_id = await _create_project_with_pm(ctx["tmp_path"], ctx["ws_root"])

    # PM Agent：脚本化返回 PM_OUTPUT
    pm_llm = FakeProvider(script={"text": json.dumps(PM_OUTPUT, ensure_ascii=False)})
    pm_agent = PMAgent(pm_llm)

    # 其他 Agent：ScriptedAgent（直接成功）
    registry = AgentRegistry()
    registry.register(pm_agent)
    for role in [AgentRole.ARCHITECT, AgentRole.BACKEND, AgentRole.FRONTEND,
                 AgentRole.TEST, AgentRole.REVIEW, AgentRole.GIT]:
        registry.register(ScriptedAgent(role))

    event_bus = EventBus()
    memory = MemoryService(ctx["ws_root"])

    orch = Orchestrator(project_id, registry, event_bus, memory, ctx["settings"])
    result = await orch.run()

    assert result == ProjectStatus.COMPLETED

    # 验证 PM 创建了后续任务
    async with db_mod.async_session_factory() as db:
        from sqlalchemy import select
        res = await db.execute(select(Task).where(Task.project_id == project_id))
        tasks = list(res.scalars().all())
        # 应该有 7 个任务（1 PM + 6 下游）
        assert len(tasks) == 7, f"Expected 7 tasks, got {len(tasks)}"
        for t in tasks:
            assert t.status == TaskStatus.SUCCESS, f"Task {t.id} ({t.agent_role}) expected SUCCESS, got {t.status.value}"

    # 验证 PM Agent 被调用
    assert pm_agent._llm.call_count >= 1


@pytest.mark.asyncio
async def test_pm_parallel_execution(setup_env):
    """验证 backend + frontend 并行执行（都依赖 architect）。"""
    ctx = setup_env
    project_id = await _create_project_with_pm(ctx["tmp_path"], ctx["ws_root"])

    pm_llm = FakeProvider(script={"text": json.dumps(PM_OUTPUT, ensure_ascii=False)})
    pm_agent = PMAgent(pm_llm)

    registry = AgentRegistry()
    registry.register(pm_agent)
    executed_roles = []

    class TrackingAgent(ScriptedAgent):
        async def run(self, ctx_agent):
            executed_roles.append(ctx_agent.agent_role.value)
            return await super().run(ctx_agent)

    for role in [AgentRole.ARCHITECT, AgentRole.BACKEND, AgentRole.FRONTEND,
                 AgentRole.TEST, AgentRole.REVIEW, AgentRole.GIT]:
        registry.register(TrackingAgent(role))

    orch = Orchestrator(project_id, registry, EventBus(), MemoryService(ctx["ws_root"]), ctx["settings"])
    await orch.run()

    # 验证 backend 和 frontend 都被执行了
    assert "backend" in executed_roles
    assert "frontend" in executed_roles
    # 验证顺序：architect 在 backend/frontend 之前
    arch_idx = executed_roles.index("architect")
    be_idx = executed_roles.index("backend")
    fe_idx = executed_roles.index("frontend")
    assert arch_idx < be_idx
    assert arch_idx < fe_idx


@pytest.mark.asyncio
async def test_pm_invalid_output(setup_env):
    """PM 输出无效 JSON → 任务 FAILED → 项目 FAILED。"""
    ctx = setup_env
    project_id = await _create_project_with_pm(ctx["tmp_path"], ctx["ws_root"])

    pm_llm = FakeProvider(script={"text": "not json at all"})
    pm_agent = PMAgent(pm_llm)

    registry = AgentRegistry()
    registry.register(pm_agent)
    # 其他 Agent 不会被调用，但需要注册以避免 registry 找不到
    for role in [AgentRole.ARCHITECT, AgentRole.BACKEND, AgentRole.FRONTEND]:
        registry.register(ScriptedAgent(role))

    orch = Orchestrator(project_id, registry, EventBus(), MemoryService(ctx["ws_root"]), ctx["settings"])
    result = await orch.run()

    assert result == ProjectStatus.FAILED


@pytest.mark.asyncio
async def test_pm_output_saved_to_memory(setup_env):
    """PM 输出应保存到 Project Memory。"""
    ctx = setup_env
    project_id = await _create_project_with_pm(ctx["tmp_path"], ctx["ws_root"])

    pm_llm = FakeProvider(script={"text": json.dumps(PM_OUTPUT, ensure_ascii=False)})
    pm_agent = PMAgent(pm_llm)

    registry = AgentRegistry()
    registry.register(pm_agent)
    for role in [AgentRole.ARCHITECT, AgentRole.BACKEND, AgentRole.FRONTEND,
                 AgentRole.TEST, AgentRole.REVIEW, AgentRole.GIT]:
        registry.register(ScriptedAgent(role))

    memory = MemoryService(ctx["ws_root"])
    orch = Orchestrator(project_id, registry, EventBus(), memory, ctx["settings"])
    await orch.run()

    pm_mem = memory.get_project_memory(project_id)
    assert "pm_output" in pm_mem
    assert pm_mem["project_name"] == "班费管理系统"


@pytest.mark.parametrize("invalid", ["missing_role", "unknown_role", "duplicate", "bad_dependency", "cycle", "bypass_review"])
async def test_pm_rejects_invalid_plan(invalid):
    from copy import deepcopy
    output = deepcopy(PM_OUTPUT)
    tasks = output["tasks"]
    if invalid == "missing_role":
        tasks.pop()
    elif invalid == "unknown_role":
        tasks.append({"role": "unknown", "depends_on": []})
    elif invalid == "duplicate":
        tasks.append(deepcopy(tasks[1]))
    elif invalid == "bad_dependency":
        tasks[1]["depends_on"] = ["architect_task_id_placeholder"]
    elif invalid == "cycle":
        tasks[0]["depends_on"] = ["git"]
    else:
        tasks[-1]["depends_on"] = ["backend"]
    agent = PMAgent(FakeProvider(script={"text": json.dumps(output)}))
    result = await agent.run(AgentContext(
        task_id="pm", project_id="p", agent_role=AgentRole.PM,
        title="需求", description="测试",
    ))
    assert result.status == TaskStatus.FAILED
    assert result.error


async def test_real_agents_receive_upstream_json(setup_env):
    """使用真实 Agent 类和确定性模型输出，验证实际 Prompt 与文件交接。"""
    from app.agents.architect import ArchitectAgent
    from app.agents.backend import BackendAgent
    from app.agents.frontend import FrontendAgent
    ctx = setup_env
    project_id = await _create_project_with_pm(ctx["tmp_path"], ctx["ws_root"])
    arch_output = {
        "tech_stack": {"backend": "FastAPI"},
        "api_design": [{"method": "GET", "path": "/api/members"}],
        "database_schema": [{"table": "members"}],
        "architecture_doc": "# Member service",
    }
    pm_llm = FakeProvider(script={"text": json.dumps(PM_OUTPUT)})
    arch_llm = FakeProvider(script={"text": json.dumps(arch_output)})
    backend_llm = FakeProvider(script={"text": json.dumps({"files": [
        {"path": "app.py", "content": "# generated backend\n"},
    ]})})
    frontend_llm = FakeProvider(script={"text": json.dumps({"files": [
        {"path": "index.html", "content": "<h1>Members</h1>"},
    ]})})
    registry = AgentRegistry()
    for agent in (PMAgent(pm_llm), ArchitectAgent(arch_llm), BackendAgent(backend_llm), FrontendAgent(frontend_llm)):
        registry.register(agent)
    for role in (AgentRole.TEST, AgentRole.REVIEW, AgentRole.GIT):
        registry.register(ScriptedAgent(role))
    orch = Orchestrator(project_id, registry, EventBus(), MemoryService(ctx["ws_root"]), ctx["settings"])
    assert await orch.run() == ProjectStatus.COMPLETED
    assert "FR-1" in arch_llm.last_messages[-1].content
    assert "/api/members" in backend_llm.last_messages[-1].content
    assert "/api/members" in frontend_llm.last_messages[-1].content
    assert "members" in frontend_llm.last_messages[-1].content
    workspace = Path(ctx["ws_root"]) / "projects" / project_id
    assert (workspace / "architecture.md").is_file()
    assert (workspace / "src/backend/app.py").is_file()
    assert (workspace / "src/frontend/index.html").is_file()
