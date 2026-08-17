"""Backend Agent：后端代码生成。

基于架构设计生成 FastAPI 后端代码（app.py + models.py + routes/）。
代码写入 workspace/projects/{id}/src/backend/。
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

from app.agents import AgentContext, AgentResult, BaseAgent
from app.llm import ChatMessage, LLMProvider
from app.models import AgentRole, TaskStatus

logger = logging.getLogger("madp.agents.backend")

BACKEND_SYSTEM_PROMPT = """你是一个资深后端工程师（Backend Agent）。基于架构设计，生成完整的后端代码。

输出格式要求（严格 JSON，不要输出其他内容）：
{
  "files": [
    {"path": "app.py", "content": "完整的 Python 代码内容"},
    {"path": "models.py", "content": "完整的 SQLAlchemy ORM 代码"},
    {"path": "routes/xxx.py", "content": "路由代码"},
    {"path": "requirements.txt", "content": "依赖列表"},
    {"path": "tests/test_api.py", "content": "pytest 测试代码"},
    {"path": "README.md", "content": "项目说明"}
  ],
  "summary": "实现概述"
}

注意：
- 所有代码必须可运行（import 正确、语法无误）
- 使用 FastAPI + SQLAlchemy + Pydantic v2
- 每个路由文件独立（不把所有路由塞进一个文件）
- tests/ 中必须有真实可执行的 pytest 测试
- requirements.txt 列出所有依赖
- 不使用任何 mock、TODO、空函数
"""


class BackendAgent(BaseAgent):
    role = AgentRole.BACKEND

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def run(self, ctx: AgentContext) -> AgentResult:
        try:
            arch_data = ctx.input_data or {}
            messages = [
                ChatMessage(role="system", content=BACKEND_SYSTEM_PROMPT),
                ChatMessage(role="user", content=(
                    f"项目名称：{arch_data.get('project_name', 'unknown')}\n"
                    f"架构设计：\n{json.dumps(arch_data, ensure_ascii=False, indent=2)[:6000]}\n\n"
                    f"请生成完整后端代码。"
                )),
            ]

            schema = {
                "type": "object",
                "required": ["files"],
            }

            result = await self._llm.generate_json(messages, schema=schema, max_tokens=8000)

            # 写入文件到工作区
            ws = Path(ctx.workspace_path) / "src" / "backend"
            ws.mkdir(parents=True, exist_ok=True)
            files_written = []
            for f in result.get("files", []):
                fpath = ws / f["path"]
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(f["content"], encoding="utf-8")
                files_written.append(f["path"])
                logger.info("Wrote %s", fpath)

            return AgentResult(
                status=TaskStatus.SUCCESS,
                output_data={"files_written": files_written, "summary": result.get("summary", "")},
            )

        except Exception as e:
            logger.exception("Backend Agent failed")
            return AgentResult(status=TaskStatus.FAILED, error=str(e))
