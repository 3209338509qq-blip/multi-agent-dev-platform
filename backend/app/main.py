"""FastAPI 入口：挂载 API 路由 + 生命周期管理。"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.database import init_db
from app.services.event_bus import event_bus

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("madp")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时建表 + 注入事件持久化回调。"""
    await init_db()

    # 注入事件持久化回调
    async def persist_event(event):
        from app.database import async_session_factory
        from app.models import Event as DbEvent
        async with async_session_factory() as db:
            db_event = DbEvent(
                project_id=event.project_id,
                task_id=event.task_id,
                run_id=event.run_id,
                type=event.type,
                payload=event.payload,
                ts=event.ts,
            )
            db.add(db_event)
            await db.flush()
            db_event.seq = db_event.id
            await db.commit()
            return db_event.id

    app.state.project_run_lock = asyncio.Lock()
    app.state.project_runs = {}
    event_bus.set_persist_fn(persist_event)
    logger.info("Platform started (v%s, sandbox=%s)", __version__, settings.sandbox_backend)
    try:
        yield
    finally:
        await shutdown_project_runs(app)
        event_bus.set_persist_fn(None)
        logger.info("Platform shutting down")


app = FastAPI(
    title="Multi-Agent Dev Platform",
    version=__version__,
    description="输入软件需求，自动完成 需求分析→架构→编码→测试→Review→Git 交付 的闭环平台",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载 API 路由
from app.api.projects import router as projects_router, shutdown_project_runs
from app.api.websocket import router as ws_router
app.include_router(projects_router)
app.include_router(ws_router)


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {
        "status": "ok",
        "service": "multi-agent-dev-platform",
        "version": __version__,
        "sandbox_backend": settings.sandbox_backend,
    }
