"""PM Agent：需求分析 + 任务拆解。

职责：理解用户需求 → 功能/非功能需求 → 验收标准 → 任务拆解（含依赖）。
输出结构化 JSON，自动创建后续任务到数据库。
"""
from __future__ import annotations
import json
import logging
from typing import Any

from app.agents import AgentContext, AgentResult, BaseAgent
from app.llm import ChatMessage, LLMProvider
from app.models import AgentRole, TaskStatus

logger = logging.getLogger("madp.agents.pm")

PM_SYSTEM_PROMPT = """你是一个资深产品经理（PM Agent）。你的任务是分析用户的软件需求并输出结构化 JSON。

输出格式要求（严格 JSON，不要输出其他内容）：
{
  "project_name": "项目名称",
  "description": "一句话项目描述",
  "requirements": [
    {"id": "FR-1", "type": "functional", "description": "功能需求描述", "priority": "high/medium/low"},
    {"id": "NFR-1", "type": "non_functional", "description": "非功能需求描述", "priority": "high/medium/low"}
  ],
  "acceptance_criteria": ["验收标准1", "验收标准2"],
  "tasks": [
    {"role": "architect", "title": "任务标题", "description": "任务描述", "depends_on": []},
    {"role": "backend", "title": "任务标题", "description": "任务描述", "depends_on": ["architect_task_id_placeholder"]},
    {"role": "frontend", "title": "任务标题", "description": "任务描述", "depends_on": ["architect_task_id_placeholder"]},
    {"role": "test", "title": "任务标题", "description": "任务描述", "depends_on": ["backend_task_id_placeholder", "frontend_task_id_placeholder"]},
    {"role": "review", "title": "代码审查", "description": "审查全部代码质量", "depends_on": ["test_task_id_placeholder"]},
    {"role": "git", "title": "Git 提交", "description": "合并分支到 main", "depends_on": ["review_task_id_placeholder"]}
  ]
}

注意：
- tasks 中 depends_on 使用 role 名称作为占位符（如 "architect"），系统会自动替换为真实 task id
- task 角色必须是以下之一：architect, backend, frontend, test, review, debug, git
- 第一个 task 必须是 architect（架构设计）
- backend 和 frontend 可以并行（都依赖 architect）
- test 依赖 backend 和 frontend
- review 依赖 test
- git 依赖 review
"""


class PMAgent(BaseAgent):
    role = AgentRole.PM

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def run(self, ctx: AgentContext) -> AgentResult:
        try:
            requirement = (ctx.input_data or {}).get("requirement", ctx.description)
            messages = [
                ChatMessage(role="system", content=PM_SYSTEM_PROMPT),
                ChatMessage(role="user", content=f"请分析以下软件需求：\n\n{requirement}"),
            ]

            schema = {
                "type": "object",
                "required": ["project_name", "requirements", "tasks", "acceptance_criteria"],
                "properties": {
                    "project_name": {"type": "string"},
                    "description": {"type": "string"},
                    "requirements": {"type": "array"},
                    "acceptance_criteria": {"type": "array"},
                    "tasks": {"type": "array"},
                },
            }

            result = await self._llm.generate_json(messages, schema=schema, max_tokens=8000)

            # 验证 tasks 结构
            tasks = result.get("tasks", [])
            if not tasks:
                return AgentResult(
                    status=TaskStatus.FAILED,
                    error="PM 未生成任何任务",
                    prompt_tokens=self._llm.count_tokens(str(messages)),
                )

            # 验证第一个 task 是 architect
            if tasks[0].get("role") != "architect":
                return AgentResult(
                    status=TaskStatus.FAILED,
                    error=f"第一个任务必须是 architect，但得到 {tasks[0].get('role')}",
                )

            return AgentResult(
                status=TaskStatus.SUCCESS,
                output_data=result,
                prompt_tokens=result.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=result.get("usage", {}).get("completion_tokens", 0),
            )

        except Exception as e:
            logger.exception("PM Agent failed")
            return AgentResult(status=TaskStatus.FAILED, error=str(e))
