"""Frontend Agent：前端代码生成。

基于架构设计生成前端代码。
优先生成单文件 HTML（嵌入式 JS/CSS），复杂项目生成 React 代码。
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

from app.agents import AgentContext, AgentResult, BaseAgent
from app.llm import ChatMessage, LLMProvider
from app.models import AgentRole, TaskStatus

logger = logging.getLogger("madp.agents.frontend")

FRONTEND_SYSTEM_PROMPT = """你是一个资深前端工程师（Frontend Agent）。基于架构设计，生成前端代码。

输出格式要求（严格 JSON，不要输出其他内容）：
{
  "files": [
    {"path": "index.html", "content": "完整的 HTML（含嵌入式 CSS 和 JS）"},
    {"path": "README.md", "content": "前端说明"}
  ],
  "summary": "实现概述"
}

技术约束：
- 优先使用单文件 HTML（index.html 含嵌入式 CSS/JS），适合简单项目
- CSS 使用内联样式或 <style> 标签
- JS 使用原生 fetch 调用后端 API（/api/xxx）
- 响应式设计（支持手机和电脑）
- 所有 API 调用处理错误状态
- 不要使用 CDN 依赖（离线可运行）
- 如果项目确实复杂（如需要多页面路由），才使用 React+Vite
"""


class FrontendAgent(BaseAgent):
    role = AgentRole.FRONTEND

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def run(self, ctx: AgentContext) -> AgentResult:
        try:
            arch_data = ctx.input_data or {}
            messages = [
                ChatMessage(role="system", content=FRONTEND_SYSTEM_PROMPT),
                ChatMessage(role="user", content=(
                    f"项目名称：{arch_data.get('project_name', 'unknown')}\n"
                    f"API 设计：{json.dumps(arch_data.get('api_design', []), ensure_ascii=False)}\n"
                    f"数据库模型：{json.dumps(arch_data.get('database_schema', []), ensure_ascii=False)[:2000]}\n\n"
                    f"请生成前端代码。"
                )),
            ]

            schema = {"type": "object", "required": ["files"]}
            result = await self._llm.generate_json(messages, schema=schema, max_tokens=8000)

            ws = Path(ctx.workspace_path) / "src" / "frontend"
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
            logger.exception("Frontend Agent failed")
            return AgentResult(status=TaskStatus.FAILED, error=str(e))
