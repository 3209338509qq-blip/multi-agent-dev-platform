"""三层记忆服务（JSON 文件持久化）。

Project Memory: 项目背景、技术决策、验收标准
Task Memory:     任务输入/输出/状态历史
Agent Memory:    各角色历史操作摘要
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("madp.memory")


class MemoryService:
    def __init__(self, workspace_root: str) -> None:
        self._workspace_root = Path(workspace_root)

    def _memory_path(self, project_id: str) -> Path:
        return self._workspace_root / "projects" / project_id / ".agent" / "memory.json"

    def _load(self, project_id: str) -> dict[str, Any]:
        path = self._memory_path(project_id)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("corrupt memory file: %s", path)
        return {"project": {}, "tasks": {}, "agents": {}}

    def _save(self, project_id: str, data: dict[str, Any]) -> None:
        path = self._memory_path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_project_memory(self, project_id: str) -> dict[str, Any]:
        return self._load(project_id).get("project", {})

    def set_project_memory(self, project_id: str, key: str, value: Any) -> None:
        data = self._load(project_id)
        data.setdefault("project", {})[key] = value
        self._save(project_id, data)

    def get_task_memory(self, project_id: str, task_id: str) -> dict[str, Any]:
        return self._load(project_id).get("tasks", {}).get(task_id, {})

    def set_task_memory(self, project_id: str, task_id: str, key: str, value: Any) -> None:
        data = self._load(project_id)
        data.setdefault("tasks", {}).setdefault(task_id, {})[key] = value
        self._save(project_id, data)

    def get_agent_memory(self, project_id: str, role: str, limit: int = 5) -> list[dict[str, Any]]:
        entries = self._load(project_id).get("agents", {}).get(role, [])
        return entries[-limit:]

    def append_agent_memory(self, project_id: str, role: str, entry: dict[str, Any]) -> None:
        data = self._load(project_id)
        data.setdefault("agents", {}).setdefault(role, []).append(entry)
        self._save(project_id, data)
