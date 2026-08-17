"""Pydantic 请求/响应模型与 Agent 产物契约。

所有 API 输入输出都通过此处的 schema 校验，确保类型安全与 OpenAPI 文档自动生成。
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, ConfigDict


class ProjectStatus(str, Enum):
    PLANNING = "planning"
    ARCHITECTING = "architecting"
    CODING = "coding"
    TESTING = "testing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class AgentRole(str, Enum):
    PM = "pm"
    ARCHITECT = "architect"
    BACKEND = "backend"
    FRONTEND = "frontend"
    TEST = "test"
    REVIEW = "review"
    DEBUG = "debug"
    GIT = "git"


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    requirement: str = Field(..., min_length=1)
    description: str = Field(default="")
    config: dict[str, Any] = Field(default_factory=dict)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    agent_role: AgentRole
    title: str
    description: str
    status: TaskStatus
    priority: int
    retry_count: int
    max_retries: int
    input_data: dict[str, Any] | None = None
    output_data: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    dependency_ids: list[str] = Field(default_factory=list)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str
    status: ProjectStatus
    requirement: str
    workspace_path: str
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ProjectDetailOut(ProjectOut):
    tasks: list[TaskOut] = Field(default_factory=list)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    type: str
    task_id: str | None = None
    payload: dict[str, Any] | None = None
    ts: datetime
