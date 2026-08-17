"""SQLAlchemy 异步引擎与会话工厂。

Phase 2 使用 aiosqlite（本地默认），compose 部署切换 PostgreSQL（asyncpg 驱动）。
DATABASE_URL 由 config.py 读取，此处仅构建引擎与会话。
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
