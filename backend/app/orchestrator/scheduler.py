"""DAG 调度器：从任务列表构建依赖图，管理就绪队列。

核心职责：
- 从 tasks 列表构建 DAG（邻接表）
- 追踪每个任务的实时状态
- 当一个任务完成时，检查其下游依赖是否全部满足 → 推入就绪队列
- 当一个任务失败时，级联标记下游为 BLOCKED
"""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from graphlib import CycleError, TopologicalSorter
from typing import Any

from app.models import TaskStatus

logger = logging.getLogger("madp.scheduler")


@dataclass
class SchedulerTask:
    id: str
    agent_role: str
    title: str
    status: TaskStatus
    depends_on: set[str] = field(default_factory=set)
    children: set[str] = field(default_factory=set)


class Scheduler:
    def __init__(self) -> None:
        self._tasks: dict[str, SchedulerTask] = {}

    def build(self, tasks: list[Any]) -> None:
        """从 ORM Task 列表构建 DAG。"""
        self._tasks.clear()
        dep_map: dict[str, set[str]] = {}
        for t in tasks:
            if t.id in self._tasks:
                raise ValueError(f"Duplicate task: {t.id}")
            dep_ids = {d.depends_on_id for d in t.dependencies}
            self._tasks[t.id] = SchedulerTask(
                id=t.id,
                agent_role=t.agent_role.value if hasattr(t.agent_role, 'value') else str(t.agent_role),
                title=t.title,
                status=t.status if isinstance(t.status, TaskStatus) else TaskStatus(t.status),
                depends_on=dep_ids,
            )
            dep_map[t.id] = dep_ids
        for task_id, deps in dep_map.items():
            missing = deps - self._tasks.keys()
            if missing:
                raise ValueError(f"Task {task_id}: missing dependencies {sorted(missing)}")
        try:
            tuple(TopologicalSorter(dep_map).static_order())
        except CycleError as exc:
            raise ValueError("Task dependencies contain a cycle") from exc
        for task_id, deps in dep_map.items():
            for dep_id in deps:
                if dep_id in self._tasks:
                    self._tasks[dep_id].children.add(task_id)

    def ready_tasks(self) -> list[str]:
        """返回 PENDING 且依赖全部 SUCCESS 的任务 id。"""
        ready = []
        for t in self._tasks.values():
            if t.status != TaskStatus.PENDING:
                continue
            deps_ok = all(
                self._tasks[d].status == TaskStatus.SUCCESS
                for d in t.depends_on if d in self._tasks
            )
            if deps_ok:
                ready.append(t.id)
        return ready

    def mark_running(self, task_id: str) -> None:
        self._tasks[task_id].status = TaskStatus.RUNNING

    def mark_success(self, task_id: str) -> list[str]:
        """标记成功，返回新变为就绪的下游任务 id 列表。"""
        self._tasks[task_id].status = TaskStatus.SUCCESS
        new_ready = []
        for child_id in self._tasks[task_id].children:
            child = self._tasks[child_id]
            if child.status != TaskStatus.PENDING:
                continue
            if all(self._tasks[d].status == TaskStatus.SUCCESS for d in child.depends_on if d in self._tasks):
                new_ready.append(child_id)
        return new_ready

    def mark_failed(self, task_id: str) -> list[str]:
        """标记失败，级联 BLOCKED 下游，返回被 BLOCKED 的 id 列表。"""
        self._tasks[task_id].status = TaskStatus.FAILED
        blocked = []
        self._cascade_block(task_id, blocked)
        return blocked

    def mark_retrying(self, task_id: str) -> None:
        self._tasks[task_id].status = TaskStatus.RETRYING

    def mark_blocked(self, task_id: str) -> None:
        self._tasks[task_id].status = TaskStatus.BLOCKED

    def mark_cancelled(self, task_id: str) -> None:
        self._tasks[task_id].status = TaskStatus.CANCELLED

    def is_terminal(self) -> bool:
        terminal = {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED}
        return all(t.status in terminal for t in self._tasks.values())

    def has_failures(self) -> bool:
        return any(t.status == TaskStatus.FAILED for t in self._tasks.values())

    def cancel_all(self) -> list[str]:
        terminal = {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED}
        cancelled = []
        for t in self._tasks.values():
            if t.status not in terminal:
                t.status = TaskStatus.CANCELLED
                cancelled.append(t.id)
        return cancelled

    def get_status(self, task_id: str) -> TaskStatus | None:
        t = self._tasks.get(task_id)
        return t.status if t else None

    def _cascade_block(self, task_id: str, blocked: list[str]) -> None:
        for child_id in self._tasks[task_id].children:
            child = self._tasks[child_id]
            if child.status == TaskStatus.PENDING:
                child.status = TaskStatus.BLOCKED
                blocked.append(child_id)
                self._cascade_block(child_id, blocked)
