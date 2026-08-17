"""Architect Agent：技术架构设计。

职责：基于 PM 输出 → 技术选型 → 系统架构 → DB 设计 → API 设计 → 目录结构 → 风险分析。
输出 architecture.md + 结构化 JSON。
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

from app.agents import AgentContext, AgentResult, BaseAgent
from app.llm import ChatMessage, LLMProvider
from app.models import AgentRole, TaskStatus

logger = logging.getLogger("madp.agents.architect")

ARCHITECT_SYSTEM_PROMPT = """你是一个资深架构师（Architect Agent）。基于 PM 的需求分析，设计完整的技术架构。

输出格式要求（严格 JSON，不要输出其他内容）：
{
  "tech_stack": {
    "backend": "技术栈描述",
    "frontend": "技术栈描述",
    "database": "数据库选择",
    "others": ["其他依赖"]
  },
  "directory_structure": "目录树（字符串，用换行分隔）",
  "api_design": [
    {"method": "GET", "path": "/api/xxx", "description": "描述", "request": null, "response": "响应描述"}
  ],
  "database_schema": [
    {"table": "表名", "columns": [{"name": "列名", "type": "类型", "constraints": "约束"}]}
  ],
  "risks": [
    {"risk": "风险描述", "mitigation": "缓解措施"}
  ],
  "architecture_doc": "完整的架构文档内容（Markdown 格式）"
}

注意：
- 技术栈优先使用：Python FastAPI + SQLAlchemy + SQLite（本地）/ PostgreSQL（生产）
- 前端使用：单文件 HTML + 嵌入式 JS/CSS（简化部署，避免 Node.js 构建复杂性）
- 或者 React + Vite（如果需求复杂度需要）
- 数据库设计要考虑索引和外键
- API 设计要 RESTful
"""

# 后端技术栈约束（引导 LLM 输出符合项目规范的技术选型）
BACKEND_TECH_GUIDE = """
技术栈约束：
- 后端必须使用 Python 3.12 + FastAPI + SQLAlchemy 2.0（与平台一致）
- 数据库使用 SQLite（本地开发）/ PostgreSQL（生产）
- 前端优先使用单文件 HTML（嵌入式 JS/CSS），复杂项目可用 React+Vite
- 测试使用 pytest
- 所有代码必须模块化（不把所有代码塞进一个文件）
"""


class ArchitectAgent(BaseAgent):
    role = AgentRole.ARCHITECT

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def run(self, ctx: AgentContext) -> AgentResult:
        try:
            pm_output = ctx.input_data or {}
            requirement = pm_output.get("requirement", ctx.description)
            project_name = pm_output.get("project_name", "unknown")

            messages = [
                ChatMessage(role="system", content=ARCHITECT_SYSTEM_PROMPT + "\n" + BACKEND_TECH_GUIDE),
                ChatMessage(role="user", content=(
                    f"项目名称：{project_name}\n"
                    f"需求分析结果：\n{json.dumps(pm_output, ensure_ascii=False, indent=2)}\n\n"
                    f"请设计技术架构。"
                )),
            ]

            schema = {
                "type": "object",
                "required": ["tech_stack", "api_design", "database_schema", "architecture_doc"],
            }

            result = await self._llm.generate_json(messages, schema=schema, max_tokens=4000)

            # 写 architecture.md 到工作区
            ws_path = Path(ctx.workspace_path)
            ws_path.mkdir(parents=True, exist_ok=True)
            arch_doc = result.get("architecture_doc", "")
            if arch_doc:
                (ws_path / "architecture.md").write_text(arch_doc, encoding="utf-8")
                logger.info("Wrote architecture.md (%d chars)", len(arch_doc))

            return AgentResult(
                status=TaskStatus.SUCCESS,
                output_data=result,
            )

        except Exception as e:
            logger.exception("Architect Agent failed")
            return AgentResult(status=TaskStatus.FAILED, error=str(e))
