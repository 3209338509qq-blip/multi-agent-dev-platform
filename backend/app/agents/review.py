"""Review Agent：代码审查。

读取代码 → Bug/安全/规范/架构检查 → 输出 review_report.md + APPROVE/REQUEST_CHANGES。
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

from app.agents import AgentContext, AgentResult, BaseAgent
from app.llm import ChatMessage, LLMProvider
from app.models import AgentRole, TaskStatus

logger = logging.getLogger("madp.agents.review")

REVIEW_SYSTEM_PROMPT = """你是一个资深代码审查员（Review Agent）。审查代码质量并输出结论。

输出格式要求（严格 JSON，不要输出其他内容）：
{
  "verdict": "APPROVE 或 REQUEST_CHANGES",
  "issues": [
    {"severity": "high/medium/low", "file": "文件路径", "line": "行号或范围", "description": "问题描述", "suggestion": "修复建议"}
  ],
  "summary": "审查总结",
  "report": "完整的 review_report.md 内容（Markdown）"
}

审查维度：
1. Bug 检查（空指针、类型错误、边界条件）
2. 安全检查（SQL 注入、XSS、硬编码密钥）
3. 代码规范（命名、注释、模块化）
4. 架构合理性（分层、耦合度）
5. 潜在性能问题
"""


class ReviewAgent(BaseAgent):
    role = AgentRole.REVIEW

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def run(self, ctx: AgentContext) -> AgentResult:
        try:
            # 读取所有源码文件
            src_path = Path(ctx.workspace_path) / "src"
            source_files = {}
            if src_path.exists():
                for f in src_path.rglob("*.py"):
                    try:
                        source_files[str(f.relative_to(src_path))] = f.read_text(encoding="utf-8")[:5000]
                    except Exception:
                        pass
                for f in src_path.rglob("*.html"):
                    try:
                        source_files[str(f.relative_to(src_path))] = f.read_text(encoding="utf-8")[:5000]
                    except Exception:
                        pass

            if not source_files:
                return AgentResult(
                    status=TaskStatus.FAILED,
                    error="未找到源码文件",
                )

            source_context = ""
            for path, content in source_files.items():
                source_context += f"\n=== {path} ===\n{content}\n"

            messages = [
                ChatMessage(role="system", content=REVIEW_SYSTEM_PROMPT),
                ChatMessage(role="user", content=f"请审查以下代码：\n{source_context[:10000]}"),
            ]

            schema = {"type": "object", "required": ["verdict", "summary"]}
            result = await self._llm.generate_json(messages, schema=schema, max_tokens=4000)

            # 写 review_report.md
            report = result.get("report", result.get("summary", ""))
            if report:
                report_path = Path(ctx.workspace_path) / "docs" / "review_report.md"
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(report, encoding="utf-8")

            verdict = result.get("verdict", "REQUEST_CHANGES")
            if verdict == "APPROVE":
                return AgentResult(
                    status=TaskStatus.SUCCESS,
                    output_data=result,
                )
            else:
                return AgentResult(
                    status=TaskStatus.FAILED,
                    error=f"Review: REQUEST_CHANGES ({len(result.get('issues', []))} issues)",
                    output_data=result,
                )

        except Exception as e:
            logger.exception("Review Agent failed")
            return AgentResult(status=TaskStatus.FAILED, error=str(e))
