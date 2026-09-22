from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from corp.config import settings


@lru_cache(maxsize=1)
def _engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
    )


@lru_cache(maxsize=1)
def _make_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_engine(), class_=AsyncSession, expire_on_commit=False)


# Lazy proxy: behaves like the old module-level async_sessionmaker but
# defers engine creation until first call, avoiding import-time side effects.
class _LazySessionmaker:
    """Proxy that creates the real async_sessionmaker on first use."""

    def __call__(self) -> AsyncSession:
        return _make_session_factory()()

    def __getattr__(self, name: str) -> object:
        return getattr(_make_session_factory(), name)


async_session: async_sessionmaker[AsyncSession] = _LazySessionmaker()  # type: ignore[assignment]


async def get_session() -> AsyncGenerator[AsyncSession]:
    async with async_session() as session:
        yield session
