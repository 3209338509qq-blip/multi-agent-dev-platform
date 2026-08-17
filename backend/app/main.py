"""FastAPI 入口：健康检查与基础中间件（Phase 1 骨架）。

后续 Phase 将挂载 /api 路由与 /ws WebSocket（见 docs/architecture.md §15）。
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("madp")

settings = get_settings()

app = FastAPI(
    title="Multi-Agent Dev Platform",
    version=__version__,
    description="输入软件需求，自动完成 需求分析→架构→编码→测试→Review→Git 交付 的闭环平台",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
async def health() -> dict:
    """存活探针：compose healthcheck 与前端启动自检共用。"""
    return {
        "status": "ok",
        "service": "multi-agent-dev-platform",
        "version": __version__,
        "sandbox_backend": settings.sandbox_backend,
    }
