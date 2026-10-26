"""调度器单测：DAG 构建、依赖解析、级联 BLOCKED。"""
import pytest
from unittest.mock import MagicMock
from app.models import TaskStatus
from app.orchestrator.scheduler import Scheduler


def _make_task(task_id: str, agent_role: str = "backend", status: TaskStatus = TaskStatus.PENDING, deps: list[str] | None = None):
    """创建模拟 ORM Task 对象。"""
    t = MagicMock()
    t.id = task_id
    t.agent_role = MagicMock()
    t.agent_role.value = agent_role
    t.title = f"Task {task_id}"
    t.status = status
    t.dependencies = []
    for dep_id in (deps or []):
        d = MagicMock()
        d.depends_on_id = dep_id
        t.dependencies.append(d)
    return t


class TestScheduler:
    def test_simple_linear_dag(self):
        """A -> B -> C（线性依赖）。"""
        sched = Scheduler()
        tasks = [
            _make_task("A", "pm"),
            _make_task("B", "architect", deps=["A"]),
            _make_task("C", "backend", deps=["B"]),
        ]
        sched.build(tasks)

        # 初始只有 A 就绪
        ready = sched.ready_tasks()
        assert ready == ["A"]

        # A 完成后 B 就绪
        sched.mark_running("A")
        new_ready = sched.mark_success("A")
        assert new_ready == ["B"]
        assert sched.ready_tasks() == ["B"]

        # B 完成后 C 就绪
        sched.mark_running("B")
        new_ready = sched.mark_success("B")
        assert new_ready == ["C"]

        # C 完成，项目结束
        sched.mark_running("C")
        new_ready = sched.mark_success("C")
        assert new_ready == []
        assert sched.is_terminal() is True

    def test_parallel_tasks(self):
        """A -> B, A -> C（B 和 C 并行）。"""
        sched = Scheduler()
        tasks = [
            _make_task("A", "architect"),
            _make_task("B", "backend", deps=["A"]),
            _make_task("C", "frontend", deps=["A"]),
        ]
        sched.build(tasks)

        sched.mark_running("A")
        new_ready = sched.mark_success("A")
        assert set(new_ready) == {"B", "C"}

    def test_cascade_block_on_failure(self):
        """A 失败 → B 和下游全部 BLOCKED。"""
        sched = Scheduler()
        tasks = [
            _make_task("A", "pm"),
            _make_task("B", "architect", deps=["A"]),
            _make_task("C", "backend", deps=["B"]),
        ]
        sched.build(tasks)

        sched.mark_running("A")
        blocked = sched.mark_failed("A")
        assert "B" in blocked
        assert "C" in blocked
        assert sched.get_status("B") == TaskStatus.BLOCKED
        assert sched.get_status("C") == TaskStatus.BLOCKED
        assert sched.has_failures() is True

    def test_cancel_all(self):
        sched = Scheduler()
        tasks = [
            _make_task("A", "pm"),
            _make_task("B", "backend", deps=["A"]),
        ]
        sched.build(tasks)
        sched.mark_running("A")
        cancelled = sched.cancel_all()
        assert "B" in cancelled
        assert sched.is_terminal() is True

    def test_diamond_dag(self):
        """Diamond: A -> B, A -> C, B -> D, C -> D。"""
        sched = Scheduler()
        tasks = [
            _make_task("A"),
            _make_task("B", deps=["A"]),
            _make_task("C", deps=["A"]),
            _make_task("D", deps=["B", "C"]),
        ]
        sched.build(tasks)

        sched.mark_running("A")
        new = sched.mark_success("A")
        assert set(new) == {"B", "C"}

        sched.mark_running("B")
        new = sched.mark_success("B")
        assert new == []  # D 还在等 C

        sched.mark_running("C")
        new = sched.mark_success("C")
        assert new == ["D"]  # D 现在就绪


@pytest.mark.parametrize("tasks, message", [
    ([_make_task("A", deps=["missing"])], "missing dependencies"),
    ([_make_task("A", deps=["B"]), _make_task("B", deps=["A"])], "cycle"),
    ([_make_task("A", deps=["A"])], "cycle"),
    ([_make_task("A"), _make_task("A")], "Duplicate"),
])
def test_reject_invalid_graph(tasks, message):
    with pytest.raises(ValueError, match=message):
        Scheduler().build(tasks)
