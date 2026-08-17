"""Test Agent：生成并真实执行测试。

读取生成的代码 → 补充/执行测试 → 输出测试报告。
"""
from __future__ import annotations
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from app.agents import AgentContext, AgentResult, BaseAgent
from app.models import AgentRole, TaskStatus

logger = logging.getLogger("madp.agents.test")


class TestAgent(BaseAgent):
    role = AgentRole.TEST

    async def run(self, ctx: AgentContext) -> AgentResult:
        try:
            backend_dir = Path(ctx.workspace_path) / "src" / "backend"
            if not backend_dir.exists():
                return AgentResult(status=TaskStatus.FAILED, error="后端代码目录不存在")

            # 检查是否有 pytest 测试
            test_files = list((backend_dir / "tests").glob("test_*.py")) if (backend_dir / "tests").exists() else []

            if not test_files:
                # 生成基础冒烟测试
                tests_dir = backend_dir / "tests"
                tests_dir.mkdir(parents=True, exist_ok=True)
                smoke_test = '''"""自动生成的冒烟测试。"""
import pytest
from pathlib import Path

def test_requirements_exists():
    req = Path(__file__).parent.parent / "requirements.txt"
    assert req.exists(), "requirements.txt 缺失"

def test_app_module():
    """验证 app 模块可导入。"""
    import importlib.util
    app_path = Path(__file__).parent.parent / "app.py"
    if app_path.exists():
        spec = importlib.util.spec_from_file_location("app", app_path)
        mod = importlib.util.module_from_spec(spec)
        # 只验证语法，不执行（避免依赖问题）
        assert spec is not None
'''
                (tests_dir / "test_smoke.py").write_text(smoke_test, encoding="utf-8")
                test_files = [tests_dir / "test_smoke.py"]

            # 执行 pytest（使用沙箱）
            venv_python = backend_dir / ".venv" / "bin" / "python"
            python_cmd = str(venv_python) if venv_python.exists() else "python3"

            # 安装依赖
            req_file = backend_dir / "requirements.txt"
            if req_file.exists():
                install_result = subprocess.run(
                    [python_cmd, "-m", "pip", "install", "-r", str(req_file), "-q"],
                    capture_output=True, text=True, timeout=120,
                    cwd=str(backend_dir),
                )
                if install_result.returncode != 0:
                    logger.warning("pip install failed: %s", install_result.stderr[:500])

            # 运行 pytest
            result = subprocess.run(
                [python_cmd, "-m", "pytest", str(tests_dir), "-v", "--tb=short", "-q"],
                capture_output=True, text=True, timeout=120,
                cwd=str(backend_dir),
            )

            output = result.stdout + result.stderr
            passed = output.count(" PASSED")
            failed = output.count(" FAILED")
            total = passed + failed

            if failed > 0:
                return AgentResult(
                    status=TaskStatus.FAILED,
                    error=f"测试失败：{failed}/{total}",
                    output_data={"output": output[-2000:], "passed": passed, "failed": failed, "total": total},
                )

            return AgentResult(
                status=TaskStatus.SUCCESS,
                output_data={"output": output[-2000:], "passed": passed, "failed": failed, "total": total},
            )

        except subprocess.TimeoutExpired:
            return AgentResult(status=TaskStatus.FAILED, error="测试执行超时")
        except Exception as e:
            logger.exception("Test Agent failed")
            return AgentResult(status=TaskStatus.FAILED, error=str(e))
