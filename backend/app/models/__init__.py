"""SQLAlchemy ORM 模型（7 张表）。

设计原则：
- 所有 JSON 字段用 sa.JSON（PostgreSQL 上映射为 jsonb）
- 时间戳统一用 UTC
- 状态字段用 Enum 字符串（与 Pydantic schema 一致）
"""
import enum
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_str() -> str:
    return uuid4().hex


class Base(DeclarativeBase):
    pass


# ---------- 枚举 ----------

class ProjectStatus(str, enum.Enum):
    PLANNING = "planning"
    ARCHITECTING = "architecting"
    CODING = "coding"
    TESTING = "testing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class AgentRole(str, enum.Enum):
    PM = "pm"
    ARCHITECT = "architect"
    BACKEND = "backend"
    FRONTEND = "frontend"
    TEST = "test"
    REVIEW = "review"
    DEBUG = "debug"
    GIT = "git"


class RunStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(32), primary_key=True, default=uuid_str)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(Enum(ProjectStatus), nullable=False, default=ProjectStatus.PLANNING)
    workspace_path = Column(String(512), nullable=False)
    repo_path = Column(String(512), nullable=True)
    config = Column(JSON, nullable=False, default=dict)
    requirement = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    tasks = relationship("Task", back_populates="project", cascade="all, delete-orphan")
    runs = relationship("AgentRun", back_populates="project", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="project", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(32), primary_key=True, default=uuid_str)
    project_id = Column(String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_role = Column(Enum(AgentRole), nullable=False)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(Enum(TaskStatus), nullable=False, default=TaskStatus.PENDING, index=True)
    priority = Column(Integer, nullable=False, default=0)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=2)
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    project = relationship("Project", back_populates="tasks")
    dependencies = relationship(
        "TaskDependency",
        foreign_keys="TaskDependency.task_id",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    runs = relationship("AgentRun", back_populates="task", cascade="all, delete-orphan")


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    task_id = Column(String(32), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    depends_on_id = Column(String(32), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)

    task = relationship("Task", foreign_keys=[task_id], back_populates="dependencies")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String(32), primary_key=True, default=uuid_str)
    task_id = Column(String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_role = Column(Enum(AgentRole), nullable=False)
    project_id = Column(String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(Enum(RunStatus), nullable=False, default=RunStatus.RUNNING)
    model = Column(String(128), nullable=True)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    task = relationship("Task", back_populates="runs")
    project = relationship("Project", back_populates="runs")


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(32), nullable=True)
    run_id = Column(String(32), nullable=True)
    type = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, nullable=True)
    seq = Column(Integer, nullable=False, default=0)
    ts = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    project = relationship("Project", back_populates="events")


class TestResult(Base):
    __tablename__ = "test_results"

    id = Column(String(32), primary_key=True, default=uuid_str)
    project_id = Column(String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(32), nullable=True)
    suite = Column(String(255), nullable=False, default="")
    total = Column(Integer, nullable=False, default=0)
    passed = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    skipped = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    output = Column(Text, nullable=True)
    ts = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class GitCommit(Base):
    __tablename__ = "git_commits"

    id = Column(String(32), primary_key=True, default=uuid_str)
    project_id = Column(String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(32), nullable=True)
    hash = Column(String(40), nullable=False)
    branch = Column(String(255), nullable=False)
    message = Column(Text, nullable=False, default="")
    files_changed = Column(JSON, nullable=True)
    ts = Column(DateTime(timezone=True), default=utcnow, nullable=False)
