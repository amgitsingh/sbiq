from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# asyncpg requires the postgresql+asyncpg:// scheme; DATABASE_URL
# (app/core/database.py) is written for the sync engine (plain
# postgresql://, psycopg2). Derived here rather than a second env var, so
# there's one source of truth for the connection target - same physical
# database either way, per this merge's "sync and async coexist" decision
# (docs/PLAN.md Phase 8).
def _to_async_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    raise ValueError(f"Unsupported DATABASE_URL scheme for the async engine: {url}")


async_engine = create_async_engine(_to_async_url(settings.DATABASE_URL))

AsyncSessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, autoflush=False, expire_on_commit=False)


async def get_async_db():
    db = AsyncSessionLocal()
    try:
        yield db
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
