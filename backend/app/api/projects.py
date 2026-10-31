"""项目 API：CRUD + 运行/取消/任务列表/事件流。

Phase 2 提供核心路由；Phase 10 扩展 metrics/git/artifacts。
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from app.database import get_db, async_session_factory
from app.models import (
    AgentRole, Event, Project, ProjectStatus, Task, TaskStatus,
)
from app.schemas import (
    EventOut, ProjectCreate, ProjectDetailOut, ProjectOut, TaskOut,
)
from app.services.event_bus import EventBus, Event as BusEvent
from app.services.event_types import PROJECT_CREATED
from app.services.memory import MemoryService

logger = logging.getLogger("madp.api.projects")

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ---------- 依赖注入 ----------

def _get_event_bus() -> EventBus:
    from app.services.event_bus import event_bus
    return event_bus

def _get_memory() -> MemoryService:
    from app.config import get_settings
    return MemoryService(get_settings().workspace_root)


# ---------- 创建项目（PM 任务自动生成）----------

@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_db)):
    settings = _get_settings()
    project_id = _generate_id()
    workspace_path = Path(settings.workspace_root) / "projects" / project_id
    (workspace_path / ".agent").mkdir(parents=True, exist_ok=True)

    project = Project(
        id=project_id,
        name=body.name,
        description=body.description,
        status=ProjectStatus.PLANNING,
        workspace_path=str(workspace_path),
        config=body.config,
        requirement=body.requirement,
    )
    db.add(project)
    await db.flush()

    # 自动生成 PM 任务（根任务，无依赖）
    pm_task = Task(
        project_id=project_id,
        agent_role=AgentRole.PM,
        title="需求分析与任务拆解",
        description=f"分析需求：{body.requirement[:200]}",
        status=TaskStatus.PENDING,
        input_data={"requirement": body.requirement, "project_name": body.name},
        max_retries=settings.task_max_retries,
    )
    db.add(pm_task)
    await db.commit()
    await db.refresh(project)

    # 广播事件
    event_bus = _get_event_bus()
    await event_bus.emit(BusEvent(
        type=PROJECT_CREATED, project_id=project_id,
        payload={"name": body.name, "task_count": 1},
    ))

    return project


# ---------- 查询 ----------

@router.get("", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{project_id}", response_model=ProjectDetailOut)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    result = await db.execute(
        select(Task).where(Task.project_id == project_id).order_by(Task.created_at)
        .options(selectinload(Task.dependencies))
    )
    tasks = list(result.scalars().all())

    task_outs = []
    for t in tasks:
        dep_ids = [d.depends_on_id for d in t.dependencies]
        out = TaskOut.model_validate(t)
        out.dependency_ids = dep_ids
        task_outs.append(out)

    # 手动构建 ProjectDetailOut，避免 Pydantic 触发 ORM 懒加载
    detail = ProjectDetailOut(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status,
        requirement=project.requirement,
        workspace_path=project.workspace_path,
        config=project.config or {},
        created_at=project.created_at,
        updated_at=project.updated_at,
        tasks=task_outs,
    )
    return detail


@router.get("/{project_id}/tasks", response_model=list[TaskOut])
async def list_tasks(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Task).where(Task.project_id == project_id).order_by(Task.created_at)
        .options(selectinload(Task.dependencies))
    )
    tasks = list(result.scalars().all())
    out = []
    for t in tasks:
        o = TaskOut.model_validate(t)
        o.dependency_ids = [d.depends_on_id for d in t.dependencies]
        out.append(o)
    return out


@router.get("/{project_id}/events", response_model=list[EventOut])
async def list_events(project_id: str, after_seq: int = 0, db: AsyncSession = Depends(get_db)):
    q = select(Event).where(Event.project_id == project_id)
    if after_seq > 0:
        q = q.where(Event.seq >= after_seq)
    q = q.order_by(Event.id).limit(500)
    result = await db.execute(q)
    return list(result.scalars().all())


# ---------- 成果（只读）----------

@router.get("/{project_id}/artifacts")
async def list_artifacts(project_id: str, db: AsyncSession = Depends(get_db)):
    return await _artifacts(project_id, db, "list")


@router.get("/{project_id}/artifacts/file")
async def preview_artifact(project_id: str, path: str, db: AsyncSession = Depends(get_db)):
    return await _artifacts(project_id, db, "preview", path)


@router.get("/{project_id}/artifacts/download")
async def download_artifacts(project_id: str, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import Response
    data = await _artifacts(project_id, db, "zip")
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="project-{project_id}.zip"',
        "Cache-Control": "no-store",
    })


async def _artifacts(project_id, db, mode, path=""):
    from starlette.concurrency import run_in_threadpool
    from app.services.artifacts import artifacts
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return await run_in_threadpool(
        artifacts, _get_settings().workspace_root, project.id, project.workspace_path, mode, path
    )


# ---------- 运行 / 取消 ----------

@router.post("/{project_id}/run")
async def run_project(project_id: str):
    """启动 Orchestrator（后台 asyncio Task）。重复调用返回 409。"""
    from app.orchestrator import Orchestrator, AgentRegistry
    from app.config import get_settings

    settings = get_settings()

    # 检查项目存在
    async with async_session_factory() as db:
        project = await db.get(Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        if project.status not in {ProjectStatus.PLANNING, ProjectStatus.FAILED}:
            raise HTTPException(409, f"Project status is {project.status.value}, cannot run")

    # 注册表（Phase 2 测试通过外部注入；此处从全局获取）
    from app.agents.registry import get_registry
    registry = get_registry()

    memory = MemoryService(settings.workspace_root)
    event_bus = _get_event_bus()

    orch = Orchestrator(project_id, registry, event_bus, memory, settings)

    # 后台运行，不阻塞请求
    asyncio.create_task(_run_orchestrator(orch, project_id))
    return {"status": "started", "project_id": project_id}


@router.post("/{project_id}/cancel")
async def cancel_project(project_id: str):
    async with async_session_factory() as db:
        project = await db.get(Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found")

    from app.orchestrator import Orchestrator
    # 简化：直接更新 DB 状态（orchestrator 的 cancel 需要实例引用，Phase 10 扩展）
    async with async_session_factory() as db:
        await db.execute(
            select(Project).where(Project.id == project_id)
        )
        from sqlalchemy import update
        await db.execute(
            update(Project).where(Project.id == project_id).values(
                status=ProjectStatus.CANCELLED, updated_at=datetime.now(timezone.utc)
            )
        )
        await db.commit()
    return {"status": "cancelled", "project_id": project_id}


# ---------- 辅助 ----------

def _get_settings():
    from app.config import get_settings
    return get_settings()

def _generate_id() -> str:
    from uuid import uuid4
    return uuid4().hex


async def _run_orchestrator(orch, project_id: str):
    """后台运行 Orchestrator 并记录结果。"""
    try:
        result = await orch.run()
        logger.info("Project %s finished: %s", project_id, result.value)
    except Exception:
        logger.exception("Orchestrator failed for project %s", project_id)
