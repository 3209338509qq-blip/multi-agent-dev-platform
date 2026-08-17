#!/usr/bin/env python3
"""完整 Demo：用真实 MiMo LLM 跑通 班费管理系统 全流程。

运行方式：cd backend && python3 ../scripts/demo.py
"""
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# 添加 backend 到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.config import Settings, get_settings
from app.database import init_db, async_session_factory, engine
from app.models import Base, Project, ProjectStatus, Task, TaskStatus, AgentRole
from app.orchestrator import Orchestrator, AgentRegistry
from app.agents.registry import create_default_registry
from app.services.event_bus import EventBus, Event
from app.services.memory import MemoryService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("demo")


def on_event(event: Event) -> None:
    """打印事件到 stdout。"""
    ts = event.ts.strftime("%H:%M:%S")
    role = (event.payload or {}).get("role", "")
    extra = ""
    if event.payload:
        keys = [k for k in event.payload if k not in ("seq", "role")]
        extra = " " + " ".join(f"{k}={event.payload[k]}" for k in keys[:3])
    print(f"  [{ts}] {event.type}{f' ({role})' if role else ''}{extra}")


async def main():
    print("=" * 60)
    print("Multi-Agent Dev Platform - 完整 Demo")
    print("需求：大学生班费管理系统")
    print("=" * 60)

    # 1. 初始化
    settings = Settings()
    print(f"\n[1/5] 初始化数据库...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. 创建项目
    print("[2/5] 创建项目...")
    project_id = f"demo-{int(time.time())}"
    ws_path = Path(settings.workspace_root) / "projects" / project_id
    (ws_path / ".agent").mkdir(parents=True, exist_ok=True)

    async with async_session_factory() as db:
        project = Project(
            id=project_id,
            name="班费管理系统",
            requirement="创建一个大学生班费管理系统，需要支持班级成员管理（添加/删除/查询成员）、收入记录（班费收取、活动退款等）、支出记录（活动支出、物资采购等）、余额统计（实时余额、收支明细）、账单查询（按时间/类型筛选）。",
            status=ProjectStatus.PLANNING,
            workspace_path=str(ws_path),
            config={},
        )
        db.add(project)
        db.add(Task(
            id=f"{project_id}-pm-0",
            project_id=project_id,
            agent_role=AgentRole.PM,
            title="需求分析与任务拆解",
            description="分析班费管理系统需求，拆解为具体任务",
            status=TaskStatus.PENDING,
            input_data={
                "requirement": project.requirement,
                "project_name": project.name,
            },
            max_retries=settings.task_max_retries,
        ))
        await db.commit()
    print(f"   项目 ID: {project_id}")
    print(f"   工作区: {ws_path}")

    # 3. 创建 Agent 注册表（使用真实 LLM）
    print("\n[3/5] 初始化 Agent 注册表（MiMo LLM）...")
    registry = create_default_registry()
    event_bus = EventBus()
    event_bus.subscribe(on_event)
    memory = MemoryService(settings.workspace_root)

    # 4. 运行编排器
    print("\n[4/5] 启动编排器（全流程）...")
    print("-" * 60)
    t0 = time.monotonic()

    orch = Orchestrator(project_id, registry, event_bus, memory, settings)
    result = await orch.run()

    duration = time.monotonic() - t0
    print("-" * 60)
    print(f"\n[5/5] 执行完成！耗时 {duration:.1f}s")
    print(f"   最终状态: {result.value}")

    # 5. 显示结果
    async with async_session_factory() as db:
        from sqlalchemy import select, func
        task_count = (await db.execute(select(func.count()).where(Task.project_id == project_id))).scalar()
        success_count = (await db.execute(select(func.count()).where(Task.project_id == project_id, Task.status == TaskStatus.SUCCESS))).scalar()
        print(f"   任务: {success_count}/{task_count} 成功")

    # 显示生成的文件
    src_path = ws_path / "src"
    if src_path.exists():
        print(f"\n   生成的代码：")
        for f in sorted(src_path.rglob("*")):
            if f.is_file():
                rel = f.relative_to(ws_path)
                size = f.stat().st_size
                print(f"     {rel} ({size} bytes)")

    # 显示 PM 输出摘要
    pm_mem = memory.get_project_memory(project_id)
    if "pm_output" in pm_mem:
        pm = pm_mem["pm_output"]
        print(f"\n   PM 分析结果：")
        print(f"     项目名称: {pm.get('project_name', 'N/A')}")
        reqs = pm.get("requirements", [])
        print(f"     需求数: {len(reqs)}")
        tasks = pm.get("tasks", [])
        print(f"     任务数: {len(tasks)}")

    if result == ProjectStatus.COMPLETED:
        print("\n✅ Demo 成功！全流程闭环完成。")
    else:
        print(f"\n❌ Demo 未完全成功（{result.value}），请检查日志。")

    return result


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result == ProjectStatus.COMPLETED else 1)
