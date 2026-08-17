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
    AgentRole, AgentRun, Event, Project, ProjectStatus, RunStatus,
    Task, TaskStatus,
)
from app.orchestrator.scheduler import Scheduler
from app.orchestrator.state_machine import TaskStateMachine, IllegalTransitionError
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
        self._running = False

    async def run(self) -> ProjectStatus:
        """主循环：构建 DAG → 调度根任务 → Worker 处理 → 处理结果 → 循环直到终态。"""
        self._running = True

        # 1. 从数据库加载项目与任务
        async with _db_module.async_session_factory() as db:
            project = await db.get(Project, self._project_id)
            if not project:
                raise ValueError(f"Project {self._project_id} not found")
            result = await db.execute(
                select(Task).where(Task.project_id == self._project_id)
                .options(selectinload(Task.dependencies))
            )
            tasks = list(result.scalars().all())
            if not tasks:
                logger.warning("No tasks found for project %s", self._project_id)
                return ProjectStatus.FAILED

        # 2. 构建调度器 DAG
        self._scheduler.build(tasks)
        self._memory.set_project_memory(self._project_id, "status", "running")

        # 3. 广播项目启动事件
        await self._event_bus.emit(BusEvent(
            type=PROJECT_STARTED,
            project_id=self._project_id,
            payload={"task_count": len(tasks)},
        ))

        # 4. 启动 Worker Pool
        workers = [
            asyncio.create_task(self._worker(i), name=f"worker-{i}")
            for i in range(self._settings.max_parallel_tasks)
        ]

        # 5. 调度根任务（无依赖）
        initial_ready = self._scheduler.ready_tasks()
        for tid in initial_ready:
            self._register_pending(tid)
            self._scheduler.mark_running(tid)
            await self._task_queue.put(tid)

        # 6. 主循环：等待结果直到终态或取消
        try:
            while not self._scheduler.is_terminal() and not self._cancel_event.is_set():
                try:
                    task_id, result = await asyncio.wait_for(
                        self._wait_any_result(), timeout=self._settings.agent_timeout_seconds
                    )
                except asyncio.TimeoutError:
                    logger.error("Project %s timed out waiting for results", self._project_id)
                    await self._fail_project("orchestrator timeout")
                    break
                except asyncio.CancelledError:
                    break

                await self._process_result(task_id, result)
        finally:
            # 关闭 workers
            for _ in workers:
                await self._task_queue.put(None)  # sentinel
            await asyncio.gather(*workers, return_exceptions=True)
            self._running = False

        # 7. 确定项目终态
        final_status = await self._finalize()
        return final_status

    async def cancel(self) -> None:
        """外部取消：级联取消所有未终态任务。"""
        self._cancel_event.set()
        cancelled = self._scheduler.cancel_all()
        async with _db_module.async_session_factory() as db:
            for tid in cancelled:
                await db.execute(
                    update(Task).where(Task.id == tid).values(
                        status=TaskStatus.CANCELLED, finished_at=datetime.now(timezone.utc)
                    )
                )
                await self._event_bus.emit(BusEvent(
                    type=TASK_CANCELLED, project_id=self._project_id, task_id=tid,
                ))
            await db.execute(
                update(Project).where(Project.id == self._project_id).values(
                    status=ProjectStatus.CANCELLED, updated_at=datetime.now(timezone.utc)
                )
            )
            await db.commit()
        await self._event_bus.emit(BusEvent(
            type=PROJECT_CANCELLED, project_id=self._project_id,
        ))

    async def _worker(self, worker_id: int) -> None:
        """Worker 协程：从队列拉取任务 id → 执行 Agent → 回报结果。"""
        while True:
            task_id = await self._task_queue.get()
            if task_id is None:  # sentinel
                break

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

        # 广播 Agent 启动
        await self._event_bus.emit(BusEvent(
            type=AGENT_STARTED, project_id=self._project_id,
            task_id=task_id, run_id=run_id,
            payload={"role": role.value},
        ))

        # 执行 Agent（带超时）
        try:
            result = await asyncio.wait_for(
                agent.run(ctx), timeout=self._settings.agent_timeout_seconds
            )
        except asyncio.TimeoutError:
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
                    status=RunStatus.SUCCESS if result.status == TaskStatus.SUCCESS else RunStatus.FAILED,
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
        """处理任务结果：更新 DB + 调度器状态 + 广播事件 + 调度下游。"""
        now = datetime.now(timezone.utc)

        if result.status == TaskStatus.SUCCESS:
            # 状态机迁移：RUNNING → SUCCESS
            TaskStateMachine.transition(self._scheduler.get_status(task_id), TaskStatus.SUCCESS, task_id)
            new_ready = self._scheduler.mark_success(task_id)

            async with _db_module.async_session_factory() as db:
                await db.execute(
                    update(Task).where(Task.id == task_id).values(
                        status=TaskStatus.SUCCESS,
                        output_data=result.output_data,
                        finished_at=now,
                    )
                )
                await db.commit()
            await self._event_bus.emit(BusEvent(
                type=TASK_COMPLETED, project_id=self._project_id, task_id=task_id,
                payload={"output_keys": list((result.output_data or {}).keys())},
            ))

            # 调度新就绪任务
            for tid in new_ready:
                self._register_pending(tid)
                self._scheduler.mark_running(tid)
                await self._task_queue.put(tid)

        elif result.status == TaskStatus.FAILED:
            # 检查重试
            async with _db_module.async_session_factory() as db:
                task = await db.get(Task, task_id)
                if task and task.retry_count < task.max_retries:
                    # 先记录失败，再重试：RUNNING → FAILED → RETRYING
                    TaskStateMachine.transition(self._scheduler.get_status(task_id), TaskStatus.FAILED, task_id)
                    TaskStateMachine.transition(TaskStatus.FAILED, TaskStatus.RETRYING, task_id)
                    self._scheduler.mark_retrying(task_id)
                    await db.execute(
                        update(Task).where(Task.id == task_id).values(
                            status=TaskStatus.RETRYING,
                            retry_count=task.retry_count + 1,
                            error=result.error,
                        )
                    )
                    await db.commit()
                    await self._event_bus.emit(BusEvent(
                        type=TASK_RETRYING, project_id=self._project_id, task_id=task_id,
                        payload={"retry_count": task.retry_count + 1, "error": result.error},
                    ))
                    # 指数退避后重新入队
                    delay = min(2 ** task.retry_count, 30)
                    await asyncio.sleep(delay)
                    self._register_pending(task_id)
                    await self._task_queue.put(task_id)
                else:
                    # 最终失败：BLOCKED + 级联下游
                    TaskStateMachine.transition(self._scheduler.get_status(task_id), TaskStatus.FAILED, task_id)
                    blocked = self._scheduler.mark_failed(task_id)
                    await db.execute(
                        update(Task).where(Task.id == task_id).values(
                            status=TaskStatus.FAILED, error=result.error, finished_at=now,
                        )
                    )
                    for bid in blocked:
                        await db.execute(
                            update(Task).where(Task.id == bid).values(status=TaskStatus.BLOCKED)
                        )
                        await self._event_bus.emit(BusEvent(
                            type=TASK_BLOCKED, project_id=self._project_id, task_id=bid,
                            payload={"blocked_by": task_id},
                        ))
                    await db.commit()
                    await self._event_bus.emit(BusEvent(
                        type=TASK_FAILED, project_id=self._project_id, task_id=task_id,
                        payload={"error": result.error},
                    ))

    async def _finalize(self) -> ProjectStatus:
        """确定项目终态并更新 DB。"""
        if self._cancel_event.is_set():
            status = ProjectStatus.CANCELLED
        elif self._scheduler.has_failures():
            status = ProjectStatus.FAILED
        else:
            status = ProjectStatus.COMPLETED

        async with _db_module.async_session_factory() as db:
            await db.execute(
                update(Project).where(Project.id == self._project_id).values(
                    status=status, updated_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        event_type = PROJECT_COMPLETED if status == ProjectStatus.COMPLETED else PROJECT_FAILED
        await self._event_bus.emit(BusEvent(
            type=event_type, project_id=self._project_id,
            payload={"final_status": status.value},
        ))
        self._memory.set_project_memory(self._project_id, "final_status", status.value)
        return status

    async def _fail_project(self, reason: str) -> None:
        """直接失败整个项目（超时/预算耗尽）。"""
        self._scheduler.cancel_all()
        async with _db_module.async_session_factory() as db:
            await db.execute(
                update(Project).where(Project.id == self._project_id).values(
                    status=ProjectStatus.FAILED, updated_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
        await self._event_bus.emit(BusEvent(
            type=PROJECT_FAILED, project_id=self._project_id,
            payload={"reason": reason},
        ))

    async def _wait_any_result(self) -> tuple[str, AgentResult]:
        """等待任意一个 pending 结果完成。"""
        if not self._pending_results:
            # 没有正在执行的任务但也没到终态：等待新任务被调度
            await asyncio.sleep(0.1)
            if self._scheduler.is_terminal():
                raise asyncio.CancelledError()
            # 重试
            return await self._wait_any_result()

        done, _ = await asyncio.wait(
            self._pending_results.values(), return_when=asyncio.FIRST_COMPLETED
        )
        for future in done:
            task_id = next(tid for tid, f in self._pending_results.items() if f is future)
            del self._pending_results[task_id]
            return task_id, future.result()
        # 不可达
        raise asyncio.CancelledError()

    def _register_pending(self, task_id: str) -> None:
        """为新入队的任务注册 pending future。"""
        self._pending_results[task_id] = asyncio.get_event_loop().create_future()
