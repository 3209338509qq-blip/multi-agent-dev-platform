"""SQLAlchemy 异步引擎与会话工厂。

Phase 2 使用 aiosqlite（本地默认），compose 部署切换 PostgreSQL（psycopg 驱动）。
DATABASE_URL 由 config.py 读取，此处仅构建引擎与会话。
"""
from pathlib import Path

from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.config import BASE_DIR, get_settings

settings = get_settings()

def resolve_database_url(database_url: str):
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        if not url.database.startswith("file:"):
            path = (BASE_DIR.parent / url.database).resolve()
            url = url.set(database=str(path))
    return url


engine = create_async_engine(
    resolve_database_url(settings.database_url),
    echo=False,
    future=True,
)

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入用：每个请求一个会话。"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """首次启动时建表（MVP 阶段，Phase 12+ 改用 Alembic）。"""
    from app.models import Base

    url = engine.url
    if url.get_backend_name() == "sqlite" and url.database and not url.database.startswith("file:"):
        if url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
