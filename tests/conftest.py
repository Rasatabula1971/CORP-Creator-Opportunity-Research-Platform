import os
import threading

# Tests must always hit an isolated corp_test database, never whatever DATABASE_URL
# a different project's shell profile happens to export. CORP_TEST_DATABASE_URL(_SYNC)
# is this suite's own override point; the hardcoded default assumes a local Postgres
# with pgvector installed.
os.environ["DATABASE_URL"] = os.environ.get(
    "CORP_TEST_DATABASE_URL", "postgresql+asyncpg://corp:corp@localhost:5433/corp_test"
)
os.environ["DATABASE_URL_SYNC"] = os.environ.get(
    "CORP_TEST_DATABASE_URL_SYNC", "postgresql://corp:corp@localhost:5433/corp_test"
)

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from corp.core.models.base import Base

TEST_DB_URL = os.environ["DATABASE_URL"]

engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
async_test_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    async with async_test_session() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def clean_db():
    """Truncate all tables before a test, then yield a fresh session."""
    import corp.core.models  # noqa: F401 — ensure all tables are registered

    table_names = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {table_names} CASCADE"))

    async with async_test_session() as session:
        yield session
        await session.rollback()


def pytest_sessionfinish(session, exitstatus):
    """Force-exit after pytest completes.

    torch / numba / LLVM spin up non-daemon threads that keep the interpreter
    alive after the test runner is done. A background timer gives pytest enough
    time to print its summary and write artifacts, then terminates the process.
    """
    def _force_exit():
        os._exit(exitstatus)

    threading.Timer(5.0, _force_exit).start()
