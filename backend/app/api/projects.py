"""项目 API：CRUD + 运行/取消/任务列表/事件流。

Phase 2 提供核心路由；Phase 10 扩展 metrics/git/artifacts。
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import database
from app.database import get_db
from app.models import (
    AgentRole, AgentRun, Project, ProjectStatus, RunStatus, Task, TaskStatus,
)
from app.schemas import (
    EventOut, ProjectCreate, ProjectDetailOut, ProjectOut, TaskOut,
)
from app.services.event_bus import EventBus, Event as BusEvent, read_project_events
from app.services.event_types import PROJECT_CANCELLED, PROJECT_CREATED, TASK_CANCELLED
from app.services.memory import MemoryService
from app.orchestrator import Orchestrator

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
    events = await read_project_events(db, project_id, after_seq)
    return [event.to_dict() for event in events]


# ---------- 运行 / 取消 ----------

@router.post("/{project_id}/run")
async def run_project(project_id: str, request: Request):
    """原子领取运行资格，再启动后台任务。"""
    from app.agents.registry import get_registry

    settings = _get_settings()
    async with request.app.state.project_run_lock:
        runs = request.app.state.project_runs
        if project_id in runs:
            raise HTTPException(409, "Project already has an active run")

        async with database.async_session_factory() as db:
            now = datetime.now(timezone.utc)
            result = await db.execute(
                update(Project).where(
                    Project.id == project_id,
                    Project.status.in_([ProjectStatus.PLANNING, ProjectStatus.FAILED, ProjectStatus.CANCELLED]),
                ).values(status=ProjectStatus.ARCHITECTING, updated_at=now).returning(Project.id)
            )
            if result.scalar_one_or_none() is None:
                project = await db.get(Project, project_id)
                if not project:
                    raise HTTPException(404, "Project not found")
                raise HTTPException(409, f"Project status is {project.status.value}, cannot run")

            # 重跑保留成功产物，重新排队失败、阻塞或上次未跑完的任务。
            await db.execute(
                update(Task).where(
                    Task.project_id == project_id, Task.status != TaskStatus.SUCCESS,
                ).values(
                    status=TaskStatus.PENDING, retry_count=0, started_at=None, finished_at=None,
                    output_data=None, error=None,
                )
            )
            await db.execute(
                update(AgentRun).where(
                    AgentRun.project_id == project_id, AgentRun.status == RunStatus.RUNNING,
                ).values(status=RunStatus.FAILED, finished_at=now, error="previous run interrupted")
            )
            orch = Orchestrator(
                project_id, get_registry(), _get_event_bus(), MemoryService(settings.workspace_root), settings,
            )
            await db.commit()

        task = asyncio.create_task(_run_orchestrator(orch, project_id, runs))
        runs[project_id] = (orch, task)
    return {"status": "started", "project_id": project_id}


@router.post("/{project_id}/cancel")
async def cancel_project(project_id: str, request: Request):
    async with request.app.state.project_run_lock:
        running = request.app.state.project_runs.get(project_id)
        if running:
            orch, task = running
            await orch.cancel()
        else:
            await _cancel_unstarted_project(project_id)

    if running and await asyncio.shield(task) != ProjectStatus.CANCELLED:
        raise HTTPException(409, "Project run has already finished")
    return {"status": "cancelled", "project_id": project_id}


async def _cancel_unstarted_project(project_id: str) -> None:
    async with database.async_session_factory() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            update(Project).where(
                Project.id == project_id, Project.status == ProjectStatus.PLANNING,
            ).values(status=ProjectStatus.CANCELLED, updated_at=now).returning(Project.id)
        )
        if result.scalar_one_or_none() is None:
            project = await db.get(Project, project_id)
            if not project:
                raise HTTPException(404, "Project not found")
            if project.status == ProjectStatus.CANCELLED:
                return
            raise HTTPException(409, f"Project status is {project.status.value}, cannot cancel")

        result = await db.execute(
            update(Task).where(
                Task.project_id == project_id, Task.status == TaskStatus.PENDING,
            ).values(status=TaskStatus.CANCELLED, finished_at=now).returning(Task.id)
        )
        cancelled_ids = list(result.scalars())
        await db.commit()

    event_bus = _get_event_bus()
    for task_id in cancelled_ids:
        await event_bus.emit(BusEvent(type=TASK_CANCELLED, project_id=project_id, task_id=task_id))
    await event_bus.emit(BusEvent(
        type=PROJECT_CANCELLED, project_id=project_id, payload={"final_status": ProjectStatus.CANCELLED.value},
    ))


async def shutdown_project_runs(app: FastAPI) -> None:
    runs = list(app.state.project_runs.values())
    for orch, _ in runs:
        await orch.cancel()
    await asyncio.gather(*(task for _, task in runs), return_exceptions=True)


# ---------- 辅助 ----------

def _get_settings():
    from app.config import get_settings
    return get_settings()


def _generate_id() -> str:
    from uuid import uuid4
    return uuid4().hex


async def _run_orchestrator(orch: Orchestrator, project_id: str, runs: dict) -> ProjectStatus:
    try:
        result = await orch.run()
        logger.info("Project %s finished: %s", project_id, result.value)
        return result
    except Exception:
        logger.exception("Orchestrator failed for project %s", project_id)
        raise
    finally:
        runs.pop(project_id, None)
