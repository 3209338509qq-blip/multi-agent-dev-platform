"""自研异步编排引擎（Phase 2 核心）。

职责：
- 从数据库构建 DAG，驱动 Scheduler 调度
- 管理 WorkerPool（asyncio 并发）
- 处理任务结果：成功→检查下游就绪；失败→重试/级联 BLOCKED
- 事件广播（所有状态变更通过 EventBus 可观测）
- 项目取消（级联取消所有未终态任务）

架构：
  Orchestrator
    ├─ Scheduler     （DAG 依赖解析 + 状态追踪）
    ├─ WorkerPool    （asyncio.Queue + Worker 协程）
    ├─ EventBus      （事件广播 + DB 持久化）
    ├─ MemoryService （三层记忆）
    └─ AgentRegistry （角色→Agent 实现映射）
"""
from __future__ import annotations
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import AgentContext, AgentResult, BaseAgent
import app.database as _db_module  # 用模块引用确保 patch 可见
from app.models import (
    AgentRole, AgentRun, Project, ProjectStatus, RunStatus,
    Task, TaskDependency, TaskStatus, uuid_str,
)
from app.orchestrator.scheduler import Scheduler
from app.orchestrator.state_machine import TaskStateMachine
from app.services.event_bus import EventBus, Event as BusEvent
from app.services.event_types import *
from app.services.memory import MemoryService

logger = logging.getLogger("madp.orchestrator")


class AgentRegistry:
    """Agent 注册表：角色 → Agent 实例映射。

    Phase 4-7 逐个注册真实 Agent；Phase 2 测试通过外部注入 ScriptedAgent。
    """
    def __init__(self) -> None:
        self._agents: dict[AgentRole, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        self._agents[agent.role] = agent

    def get(self, role: AgentRole) -> BaseAgent | None:
        return self._agents.get(role)


class Orchestrator:
    """自研异步编排引擎。

    用法：
        orch = Orchestrator(project_id, registry, event_bus, memory, settings)
        await orch.run()   # 阻塞到项目完成/失败/取消
        await orch.cancel()  # 从外部取消
    """

    def __init__(
        self,
        project_id: str,
        registry: AgentRegistry,
        event_bus: EventBus,
        memory: MemoryService,
        settings: Any,
    ) -> None:
        self._project_id = project_id
        self._registry = registry
        self._event_bus = event_bus
        self._memory = memory
        self._settings = settings
        self._scheduler = Scheduler()
        self._cancel_event = asyncio.Event()
        self._task_queue: asyncio.Queue[str] = asyncio.Queue()
        self._pending_results: dict[str, asyncio.Future[AgentResult]] = {}

    async def run(self) -> ProjectStatus:
        """运行任务图，并在写入项目终态前等待 Worker 退出。"""
        workers = []
        cancel_waiter = asyncio.create_task(self._cancel_event.wait())
        failure = None
        try:
            tasks = await self._load_tasks()
            if not tasks:
                raise RuntimeError("project has no tasks")
            if self._settings.max_parallel_tasks < 1:
                raise RuntimeError("max_parallel_tasks must be positive")

            # 旧版本可能在保存 PM 成功后、创建下游任务前退出。
            if len(tasks) == 1:
                pm = tasks[0]
                if pm.agent_role == AgentRole.PM and pm.status == TaskStatus.SUCCESS:
                    if (pm.output_data or {}).get("tasks"):
                        await self._create_downstream_tasks(pm.id, pm.output_data)
                        tasks = await self._load_tasks()

            self._scheduler.build(tasks)
            if not self._cancel_event.is_set():
                self._memory.set_project_memory(self._project_id, "status", "running")
                await self._event_bus.emit(BusEvent(
                    type=PROJECT_STARTED, project_id=self._project_id,
                    payload={"task_count": len(tasks)},
                ))
                workers = [
                    asyncio.create_task(self._worker(i), name=f"worker-{i}")
                    for i in range(self._settings.max_parallel_tasks)
                ]
                self._enqueue_ready_tasks()

            while not self._scheduler.is_terminal() and not self._cancel_event.is_set():
                if not self._pending_results:
                    raise RuntimeError("no runnable tasks remain")
                done, _ = await asyncio.wait(
                    [cancel_waiter, *self._pending_results.values()],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_waiter in done:
                    break

                for task_id, future in list(self._pending_results.items()):
                    if future in done and not self._cancel_event.is_set():
                        del self._pending_results[task_id]
                        await self._process_result(task_id, future.result())
        except asyncio.CancelledError:
            self._cancel_event.set()
        except Exception as exc:
            logger.exception("Project %s failed", self._project_id)
            failure = str(exc)
        finally:
            cancel_waiter.cancel()
            for worker in workers:
                worker.cancel()
            await asyncio.gather(cancel_waiter, *workers, return_exceptions=True)

        return await self._finalize(failure)

    async def cancel(self) -> None:
        """通知调度循环停止，并由 run() 收回 Worker 和持久化终态。"""
        self._cancel_event.set()

    def _enqueue_ready_tasks(self) -> None:
        for task_id in self._scheduler.ready_tasks():
            self._enqueue_task(task_id)

    def _enqueue_task(self, task_id: str) -> None:
        self._pending_results[task_id] = asyncio.get_running_loop().create_future()
        self._scheduler.mark_running(task_id)
        self._task_queue.put_nowait(task_id)

    async def _worker(self, worker_id: int) -> None:
        """Worker 协程：从队列拉取任务 id → 执行 Agent → 回报结果。"""
        while True:
            task_id = await self._task_queue.get()
            if self._cancel_event.is_set():
                return
            try:
                result = await self._execute_task(task_id)
            except Exception as exc:
                logger.exception("Worker %d: task %s crashed", worker_id, task_id)
                result = AgentResult(status=TaskStatus.FAILED, error=str(exc))

            # 设置结果（唤醒主循环）
            if task_id in self._pending_results:
                self._pending_results[task_id].set_result(result)

    async def _execute_task(self, task_id: str) -> AgentResult:
        """执行单个任务：查 DB → 构建上下文 → 调用 Agent → 记录运行。"""
        t0 = time.monotonic()

        async with _db_module.async_session_factory() as db:
            task = await db.get(Task, task_id)
            if not task:
                return AgentResult(status=TaskStatus.FAILED, error="task not found")

            role = task.agent_role if isinstance(task.agent_role, AgentRole) else AgentRole(task.agent_role)
            agent = self._registry.get(role)
            if not agent:
                return AgentResult(status=TaskStatus.FAILED, error=f"no agent for role {role.value}")

            # 构建执行上下文
            ctx = AgentContext(
                task_id=task.id,
                project_id=self._project_id,
                agent_role=role,
                title=task.title,
                description=task.description,
                input_data=task.input_data,
                workspace_path=self._memory._workspace_root / "projects" / self._project_id,
                project_memory=self._memory.get_project_memory(self._project_id),
                agent_memory=self._memory.get_agent_memory(self._project_id, role.value),
                task_memory=self._memory.get_task_memory(self._project_id, task.id),
            )

            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now(timezone.utc)
            task.finished_at = None

            # 创建 AgentRun 记录
            run_record = AgentRun(
                task_id=task.id,
                agent_role=role,
                project_id=self._project_id,
                status=RunStatus.RUNNING,
                started_at=datetime.now(timezone.utc),
            )
            db.add(run_record)
            await db.flush()
            run_id = run_record.id
            await db.commit()

        await self._event_bus.emit(BusEvent(
            type=TASK_STARTED, project_id=self._project_id, task_id=task_id,
        ))
        await self._event_bus.emit(BusEvent(
            type=AGENT_STARTED, project_id=self._project_id,
            task_id=task_id, run_id=run_id,
            payload={"role": role.value},
        ))

        run_status = RunStatus.FAILED
        try:
            result = await asyncio.wait_for(
                agent.run(ctx), timeout=self._settings.agent_timeout_seconds
            )
            if result.status == TaskStatus.SUCCESS:
                run_status = RunStatus.SUCCESS
        except asyncio.TimeoutError:
            run_status = RunStatus.TIMEOUT
            result = AgentResult(status=TaskStatus.FAILED, error="agent timeout")
        except Exception as exc:
            logger.exception("Agent %s crashed on task %s", role.value, task_id)
            result = AgentResult(status=TaskStatus.FAILED, error=str(exc))

        duration_ms = int((time.monotonic() - t0) * 1000)
        result.duration_ms = duration_ms

        # 更新 AgentRun 记录
        async with _db_module.async_session_factory() as db:
            await db.execute(
                update(AgentRun).where(AgentRun.id == run_id).values(
                    status=run_status,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    duration_ms=duration_ms,
                    model=result.model,
                    error=result.error,
                    finished_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        # 写入 Agent Memory
        self._memory.append_agent_memory(self._project_id, role.value, {
            "task_id": task_id,
            "status": result.status.value,
            "duration_ms": duration_ms,
            "error": result.error,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

        # 广播 Agent 完成/失败
        await self._event_bus.emit(BusEvent(
            type=AGENT_COMPLETED if result.status == TaskStatus.SUCCESS else AGENT_FAILED,
            project_id=self._project_id, task_id=task_id, run_id=run_id,
            payload={"status": result.status.value, "duration_ms": duration_ms},
        ))

        return result

    async def _process_result(self, task_id: str, result: AgentResult) -> None:
        """提交任务结果后再广播，避免在 SQLite 写事务内等待另一条写连接。"""
        now = datetime.now(timezone.utc)
        previous = self._scheduler.get_status(task_id)
        if result.status == TaskStatus.SUCCESS:
            TaskStateMachine.transition(previous, TaskStatus.SUCCESS, task_id)
            async with _db_module.async_session_factory() as db:
                task = await db.get(Task, task_id)
                task.status = TaskStatus.SUCCESS
                task.output_data = result.output_data
                task.error = None
                task.finished_at = now
                is_pm = task.agent_role == AgentRole.PM and bool(result.output_data)
                if is_pm:
                    await self._insert_downstream_tasks(db, task_id, result.output_data)
                await db.commit()

            self._scheduler.mark_success(task_id)
            if is_pm:
                self._save_pm_output(result.output_data)
                self._scheduler.build(await self._load_tasks())
                for pending_id in self._pending_results:
                    self._scheduler.mark_running(pending_id)

            await self._event_bus.emit(BusEvent(
                type=TASK_COMPLETED, project_id=self._project_id, task_id=task_id,
                payload={"output_keys": list((result.output_data or {}).keys())},
            ))
            if not self._cancel_event.is_set():
                self._enqueue_ready_tasks()
            return

        TaskStateMachine.transition(previous, TaskStatus.FAILED, task_id)
        async with _db_module.async_session_factory() as db:
            task = await db.get(Task, task_id)
            task.error = result.error
            retry = task.retry_count < task.max_retries
            if retry:
                TaskStateMachine.transition(TaskStatus.FAILED, TaskStatus.RETRYING, task_id)
                self._scheduler.mark_retrying(task_id)
                task.status = TaskStatus.RETRYING
                task.retry_count += 1
            else:
                blocked = self._scheduler.mark_failed(task_id)
                task.status = TaskStatus.FAILED
                task.finished_at = now
                if blocked:
                    await db.execute(
                        update(Task).where(Task.id.in_(blocked)).values(
                            status=TaskStatus.BLOCKED, finished_at=now,
                        )
                    )
            await db.commit()

        if retry:
            await self._event_bus.emit(BusEvent(
                type=TASK_RETRYING, project_id=self._project_id, task_id=task_id,
                payload={"retry_count": task.retry_count, "error": result.error},
            ))
            delay = min(2 ** (task.retry_count - 1), 30)
            try:
                await asyncio.wait_for(self._cancel_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                self._enqueue_task(task_id)
            return

        for blocked_id in blocked:
            await self._event_bus.emit(BusEvent(
                type=TASK_BLOCKED, project_id=self._project_id, task_id=blocked_id,
                payload={"blocked_by": task_id},
            ))
        await self._event_bus.emit(BusEvent(
            type=TASK_FAILED, project_id=self._project_id, task_id=task_id,
            payload={"error": result.error},
        ))

    async def _finalize(self, failure: str | None) -> ProjectStatus:
        cancelled = self._cancel_event.is_set()
        if cancelled:
            status = ProjectStatus.CANCELLED
            event_type = PROJECT_CANCELLED
        elif failure is not None or self._scheduler.has_failures():
            status = ProjectStatus.FAILED
            event_type = PROJECT_FAILED
        else:
            status = ProjectStatus.COMPLETED
            event_type = PROJECT_COMPLETED

        now = datetime.now(timezone.utc)
        async with _db_module.async_session_factory() as db:
            unfinished = await db.execute(
                update(Task).where(
                    Task.project_id == self._project_id,
                    Task.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.RETRYING]),
                ).values(
                    status=TaskStatus.CANCELLED if cancelled else TaskStatus.BLOCKED,
                    finished_at=now,
                    error=failure,
                ).returning(Task.id)
            )
            unfinished_ids = list(unfinished.scalars())
            await db.execute(
                update(AgentRun).where(
                    AgentRun.project_id == self._project_id, AgentRun.status == RunStatus.RUNNING,
                ).values(
                    status=RunStatus.CANCELLED if cancelled else RunStatus.FAILED,
                    finished_at=now,
                    error=failure,
                )
            )
            await db.execute(
                update(Project).where(Project.id == self._project_id).values(status=status, updated_at=now)
            )
            await db.commit()

        for task_id in unfinished_ids:
            await self._event_bus.emit(BusEvent(
                type=TASK_CANCELLED if cancelled else TASK_BLOCKED,
                project_id=self._project_id, task_id=task_id,
            ))
        payload = {"final_status": status.value}
        if failure is not None:
            payload["reason"] = failure
        await self._event_bus.emit(BusEvent(
            type=event_type, project_id=self._project_id, payload=payload,
        ))
        self._memory.set_project_memory(self._project_id, "final_status", status.value)
        return status

    async def _create_downstream_tasks(self, pm_task_id: str, pm_output: dict) -> None:
        async with _db_module.async_session_factory() as db:
            await self._insert_downstream_tasks(db, pm_task_id, pm_output)
            await db.commit()
        self._save_pm_output(pm_output)

    async def _insert_downstream_tasks(self, db: AsyncSession, pm_task_id: str, pm_output: dict) -> None:
        """在 PM 结果的同一事务中插入任务与依赖。"""
        tasks_def = pm_output.get("tasks", [])
        if not tasks_def:
            return

        role_to_task_id = {"pm": pm_task_id}
        for tdef in tasks_def:
            role = AgentRole(tdef["role"])
            if role.value in role_to_task_id:
                raise ValueError(f"duplicate task role: {role.value}")
            task_id = uuid_str()
            role_to_task_id[role.value] = task_id
            db.add(Task(
                id=task_id,
                project_id=self._project_id,
                agent_role=role,
                title=tdef.get("title", f"{role.value} task"),
                description=tdef.get("description", ""),
                status=TaskStatus.PENDING,
                input_data={
                    **tdef,
                    "project_name": pm_output.get("project_name", ""),
                    "requirement": pm_output.get("requirement", ""),
                },
                max_retries=self._settings.task_max_retries,
            ))

        await db.flush()
        for tdef in tasks_def:
            task_id = role_to_task_id[tdef["role"]]
            for dep_role in dict.fromkeys(tdef.get("depends_on", [])):
                dep_id = role_to_task_id.get(dep_role)
                if dep_id:
                    db.add(TaskDependency(task_id=task_id, depends_on_id=dep_id))

    def _save_pm_output(self, pm_output: dict) -> None:
        self._memory.set_project_memory(self._project_id, "pm_output", pm_output)
        self._memory.set_project_memory(self._project_id, "project_name", pm_output.get("project_name", ""))

    async def _load_tasks(self) -> list[Task]:
        async with _db_module.async_session_factory() as db:
            result = await db.execute(
                select(Task).where(Task.project_id == self._project_id)
                .options(selectinload(Task.dependencies))
            )
            return list(result.scalars())
