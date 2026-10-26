"""真实执行 pytest，验证 Test Agent 不会把执行错误当作通过。"""
from pathlib import Path

import pytest

from app.agents import AgentContext
from app.agents.test_agent import TestAgent as PipelineTestAgent
from app.models import AgentRole, TaskStatus


async def run_suite(tmp_path: Path, source: str):
    backend = tmp_path / "src" / "backend"
    (backend / "tests").mkdir(parents=True)
    (backend / "tests" / "test_generated.py").write_text(source)
    ctx = AgentContext(
        task_id="test", project_id="project", agent_role=AgentRole.TEST,
        title="测试", description="", workspace_path=str(tmp_path),
    )
    return await PipelineTestAgent().run(ctx)


@pytest.mark.parametrize(("source", "expected", "passed", "failed"), [
    ("def test_ok():\n    assert 1 + 1 == 2\n", TaskStatus.SUCCESS, 1, 0),
    ("def test_bad():\n    assert False\n", TaskStatus.FAILED, 0, 1),
    ("import nonexistent_generated_dependency\n", TaskStatus.FAILED, 0, 1),
    ("# no tests here\n", TaskStatus.FAILED, 0, 0),
    ("import pytest\n@pytest.mark.skip\ndef test_skipped():\n    pass\n", TaskStatus.FAILED, 0, 0),
])
async def test_real_pytest_outcomes(tmp_path, source, expected, passed, failed):
    result = await run_suite(tmp_path, source)
    assert result.status == expected, result.error
    assert result.output_data["passed"] == passed
    assert result.output_data["failed"] == failed


async def test_smoke_checks_python_syntax(tmp_path):
    backend = tmp_path / "src" / "backend"
    backend.mkdir(parents=True)
    (backend / "app.py").write_text("def broken(:\n")
    # No requirements file: the smoke suite must also flag the missing manifest.
    ctx = AgentContext(
        task_id="test", project_id="project", agent_role=AgentRole.TEST,
        title="测试", description="", workspace_path=str(tmp_path),
    )
    result = await PipelineTestAgent().run(ctx)
    assert result.status == TaskStatus.FAILED
    assert result.output_data["failed"] == 2


async def test_install_failure_stops_before_pytest(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    import app.agents.test_agent as agent_module
    backend = tmp_path / "src/backend"
    backend.mkdir(parents=True)
    (backend / "requirements.txt").write_text("nonexistent-package\n")
    command = AsyncMock(return_value=(1, "dependency resolution failed"))
    monkeypatch.setattr(agent_module, "_run_command", command)
    result = await PipelineTestAgent().run(AgentContext(
        task_id="test", project_id="project", agent_role=AgentRole.TEST,
        title="测试", description="", workspace_path=str(tmp_path),
    ))
    assert result.status == TaskStatus.FAILED
    assert result.output_data["phase"] == "install"
    assert command.await_count == 1


async def test_nonzero_exit_without_failed_cases_is_failure(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    import app.agents.test_agent as agent_module
    command = AsyncMock(return_value=(4, "pytest command line error"))
    monkeypatch.setattr(agent_module, "_run_command", command)
    result = await run_suite(tmp_path, "def test_ok():\n    pass\n")
    assert result.status == TaskStatus.FAILED
    assert result.output_data["exit_code"] == 4
    assert result.output_data["report_valid"] is False
