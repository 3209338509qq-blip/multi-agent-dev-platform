"""Task 状态机：强制合法迁移，非法迁移抛 IllegalTransitionError。

迁移表严格按 docs/architecture.md §5 实现。
"""
from __future__ import annotations
import logging
from app.models import TaskStatus

logger = logging.getLogger("madp.state_machine")


class IllegalTransitionError(Exception):
    def __init__(self, task_id: str, from_status: TaskStatus, to_status: TaskStatus) -> None:
        self.task_id = task_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Task {task_id}: illegal transition {from_status.value} -> {to_status.value}")


_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING:   {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.CANCELLED},
    TaskStatus.RUNNING:   {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.RETRYING, TaskStatus.CANCELLED},
    TaskStatus.FAILED:    {TaskStatus.RETRYING, TaskStatus.BLOCKED},
    TaskStatus.RETRYING:  {TaskStatus.RUNNING, TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.BLOCKED:   {TaskStatus.PENDING, TaskStatus.CANCELLED},
    TaskStatus.SUCCESS:   set(),
    TaskStatus.CANCELLED: set(),
}


class TaskStateMachine:
    @staticmethod
    def validate(current: TaskStatus, target: TaskStatus) -> bool:
        return target in _TRANSITIONS.get(current, set())

    @staticmethod
    def transition(current: TaskStatus, target: TaskStatus, task_id: str = "") -> TaskStatus:
        if not TaskStateMachine.validate(current, target):
            raise IllegalTransitionError(task_id, current, target)
        logger.debug("Task %s: %s -> %s", task_id, current.value, target.value)
        return target
