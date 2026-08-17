"""Debug Agent：读取测试错误 → 分析根因 → 修复代码。

输入：测试错误输出 + 相关代码文件。
输出：修复后的代码文件。
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

from app.agents import AgentContext, AgentResult, BaseAgent
from app.llm import ChatMessage, LLMProvider
from app.models import AgentRole, TaskStatus

logger = logging.getLogger("madp.agents.debug")

DEBUG_SYSTEM_PROMPT = """你是一个资深调试工程师（Debug Agent）。根据测试失败信息，分析根因并修复代码。

输出格式要求（严格 JSON，不要输出其他内容）：
{
  "root_cause": "根因分析",
  "fixes": [
    {"path": "文件路径", "content": "修复后的完整文件内容"}
  ],
  "explanation": "修复说明"
}

注意：
- 分析测试错误和 stack trace
- 读取相关源码文件
- 输出修复后的完整文件内容（不是 diff）
- 如果是依赖缺失，在 requirements.txt 中补充
"""


class DebugAgent(BaseAgent):
    role = AgentRole.DEBUG

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def run(self, ctx: AgentContext) -> AgentResult:
        try:
            input_data = ctx.input_data or {}
            error_output = input_data.get("error_output", "")
            source_files = input_data.get("source_files", {})

            # 构建上下文
            source_context = ""
            for path, content in source_files.items():
                source_context += f"\n=== {path} ===\n{content[:3000]}\n"

            messages = [
                ChatMessage(role="system", content=DEBUG_SYSTEM_PROMPT),
                ChatMessage(role="user", content=(
                    f"测试失败信息：\n{error_output[:3000]}\n\n"
                    f"相关源码：\n{source_context}\n\n"
                    f"请分析根因并修复。"
                )),
            ]

            schema = {"type": "object", "required": ["root_cause", "fixes"]}
            result = await self._llm.generate_json(messages, schema=schema, max_tokens=6000)

            # 应用修复
            fixes_applied = []
            for fix in result.get("fixes", []):
                fpath = Path(ctx.workspace_path) / "src" / "backend" / fix["path"]
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(fix["content"], encoding="utf-8")
                fixes_applied.append(fix["path"])
                logger.info("Applied fix to %s", fpath)

            return AgentResult(
                status=TaskStatus.SUCCESS,
                output_data={"root_cause": result.get("root_cause", ""), "fixes_applied": fixes_applied},
            )

        except Exception as e:
            logger.exception("Debug Agent failed")
            return AgentResult(status=TaskStatus.FAILED, error=str(e))
