"""状态机单测：覆盖全部合法迁移 + 非法迁移拒绝。"""
import pytest
from app.models import TaskStatus
from app.orchestrator.state_machine import TaskStateMachine, IllegalTransitionError


class TestTaskStateMachine:
    def test_pending_to_running(self):
        assert TaskStateMachine.validate(TaskStatus.PENDING, TaskStatus.RUNNING) is True
        assert TaskStateMachine.transition(TaskStatus.PENDING, TaskStatus.RUNNING, "t1") == TaskStatus.RUNNING

    def test_pending_to_blocked(self):
        assert TaskStateMachine.validate(TaskStatus.PENDING, TaskStatus.BLOCKED) is True

    def test_pending_to_cancelled(self):
        assert TaskStateMachine.validate(TaskStatus.PENDING, TaskStatus.CANCELLED) is True

    def test_running_to_success(self):
        assert TaskStateMachine.validate(TaskStatus.RUNNING, TaskStatus.SUCCESS) is True

    def test_running_to_failed(self):
        assert TaskStateMachine.validate(TaskStatus.RUNNING, TaskStatus.FAILED) is True

    def test_running_to_cancelled(self):
        assert TaskStateMachine.validate(TaskStatus.RUNNING, TaskStatus.CANCELLED) is True

    def test_failed_to_retrying(self):
        assert TaskStateMachine.validate(TaskStatus.FAILED, TaskStatus.RETRYING) is True

    def test_failed_to_blocked(self):
        assert TaskStateMachine.validate(TaskStatus.FAILED, TaskStatus.BLOCKED) is True

    def test_retrying_to_running(self):
        assert TaskStateMachine.validate(TaskStatus.RETRYING, TaskStatus.RUNNING) is True

    def test_blocked_to_pending(self):
        assert TaskStateMachine.validate(TaskStatus.BLOCKED, TaskStatus.PENDING) is True

    def test_success_is_terminal(self):
        assert TaskStateMachine.validate(TaskStatus.SUCCESS, TaskStatus.RUNNING) is False
        assert TaskStateMachine.validate(TaskStatus.SUCCESS, TaskStatus.PENDING) is False

    def test_cancelled_is_terminal(self):
        assert TaskStateMachine.validate(TaskStatus.CANCELLED, TaskStatus.RUNNING) is False

    def test_illegal_transition_raises(self):
        with pytest.raises(IllegalTransitionError) as exc_info:
            TaskStateMachine.transition(TaskStatus.SUCCESS, TaskStatus.RUNNING, "t1")
        assert exc_info.value.task_id == "t1"
        assert exc_info.value.from_status == TaskStatus.SUCCESS
        assert exc_info.value.to_status == TaskStatus.RUNNING

    def test_pending_to_success_is_illegal(self):
        """PENDING 不能直接跳到 SUCCESS（必须经过 RUNNING）。"""
        assert TaskStateMachine.validate(TaskStatus.PENDING, TaskStatus.SUCCESS) is False

    def test_pending_to_failed_is_illegal(self):
        assert TaskStateMachine.validate(TaskStatus.PENDING, TaskStatus.FAILED) is False

    def test_full_success_path(self):
        s = TaskStatus.PENDING
        s = TaskStateMachine.transition(s, TaskStatus.RUNNING, "t1")
        s = TaskStateMachine.transition(s, TaskStatus.SUCCESS, "t1")
        assert s == TaskStatus.SUCCESS

    def test_full_retry_path(self):
        s = TaskStatus.PENDING
        s = TaskStateMachine.transition(s, TaskStatus.RUNNING, "t1")
        s = TaskStateMachine.transition(s, TaskStatus.FAILED, "t1")
        s = TaskStateMachine.transition(s, TaskStatus.RETRYING, "t1")
        s = TaskStateMachine.transition(s, TaskStatus.RUNNING, "t1")
        s = TaskStateMachine.transition(s, TaskStatus.SUCCESS, "t1")
        assert s == TaskStatus.SUCCESS
