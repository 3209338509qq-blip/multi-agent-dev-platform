"""Test Agent：真实执行 pytest，以退出码和 JUnit 报告判断结果。"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import sys
import tempfile
import xml.etree.ElementTree as ET

from app.agents import AgentContext, AgentResult, BaseAgent
from app.models import AgentRole, TaskStatus

logger = logging.getLogger("madp.agents.test")

SMOKE_TEST = '''"""基础检查不等于业务验收；验证依赖清单和 Python 语法。"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def test_requirements_exists():
    assert (ROOT / "requirements.txt").is_file(), "requirements.txt 缺失"

def test_source_syntax():
    files = [p for p in ROOT.rglob("*.py")
             if not {"tests", ".venv", "venv", "__pycache__"}.intersection(p.relative_to(ROOT).parts)]
    assert files, "未找到 Python 源码"
    for path in files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
'''


async def _run_command(args: list[str], cwd: Path, timeout: float = 120) -> tuple[int, str]:
    """不阻塞事件循环；超时或取消时回收子进程。"""
    process = await asyncio.create_subprocess_exec(
        *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    return process.returncode, stdout.decode("utf-8", errors="replace")


class TestAgent(BaseAgent):
    role = AgentRole.TEST

    async def run(self, ctx: AgentContext) -> AgentResult:
        try:
            backend_dir = (Path(ctx.workspace_path) / "src" / "backend").resolve()
            if not backend_dir.is_dir():
                return AgentResult(status=TaskStatus.FAILED, error="后端代码目录不存在")

            tests_dir = backend_dir / "tests"
            test_files = list(tests_dir.rglob("test_*.py")) if tests_dir.exists() else []
            smoke_only = not test_files
            if smoke_only:
                tests_dir.mkdir(parents=True, exist_ok=True)
                (tests_dir / "test_smoke.py").write_text(SMOKE_TEST, encoding="utf-8")

            venv_python = backend_dir / ".venv" / "bin" / "python"
            python_cmd = str(venv_python) if venv_python.exists() else sys.executable
            req_file = backend_dir / "requirements.txt"
            if req_file.exists():
                code, output = await _run_command(
                    [python_cmd, "-m", "pip", "install", "-r", str(req_file), "-q"], backend_dir,
                )
                if code != 0:
                    return AgentResult(
                        status=TaskStatus.FAILED, error="依赖安装失败，测试未执行",
                        output_data={"output": output[-4000:], "exit_code": code, "phase": "install"},
                    )

            with tempfile.TemporaryDirectory(prefix="madp-pytest-") as temp_dir:
                report_path = Path(temp_dir) / "report.xml"
                code, output = await _run_command(
                    [python_cmd, "-m", "pytest", str(tests_dir), "-v", "--tb=short",
                     f"--junitxml={report_path}"], backend_dir,
                )
                counts = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
                report_valid = report_path.is_file()
                if report_valid:
                    try:
                        report = ET.parse(report_path).getroot()
                        for case in report.iter("testcase"):
                            counts["total"] += 1
                            if case.find("failure") is not None or case.find("error") is not None:
                                counts["failed"] += 1
                            elif case.find("skipped") is not None:
                                counts["skipped"] += 1
                            else:
                                counts["passed"] += 1
                    except ET.ParseError:
                        report_valid = False

            success = code == 0 and report_valid and counts["passed"] > 0 and counts["failed"] == 0
            return AgentResult(
                status=TaskStatus.SUCCESS if success else TaskStatus.FAILED,
                error=None if success else f"测试未通过（退出码 {code}，通过 {counts['passed']}，失败 {counts['failed']}）",
                output_data={**counts, "output": output[-4000:], "exit_code": code,
                             "smoke_only": smoke_only, "report_valid": report_valid},
            )
        except asyncio.TimeoutError:
            return AgentResult(status=TaskStatus.FAILED, error="测试或依赖安装超时")
        except Exception as exc:
            logger.exception("Test Agent failed")
            return AgentResult(status=TaskStatus.FAILED, error=str(exc))
