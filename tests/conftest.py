import os

# Tests must always hit an isolated corp_test database, never whatever DATABASE_URL
# a different project's shell profile happens to export. CORP_TEST_DATABASE_URL(_SYNC)
# is this suite's own override point; the hardcoded default assumes a local Postgres
# with pgvector installed.
os.environ["DATABASE_URL"] = os.environ.get(
    "CORP_TEST_DATABASE_URL", "postgresql+asyncpg://corp:corp@localhost:5432/corp_test"
)
os.environ["DATABASE_URL_SYNC"] = os.environ.get(
    "CORP_TEST_DATABASE_URL_SYNC", "postgresql://corp:corp@localhost:5432/corp_test"
)

import asyncio
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from corp.core.models.base import Base

TEST_DB_URL = os.environ["DATABASE_URL"]

engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
async_test_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_test_session() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def clean_db():
    """Truncate all tables before a test, then yield a fresh session."""
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE TABLE niche_candidate_evidence, niche_candidates, "
            "research_queries, creator_niches, campaign_niches, campaigns, "
            "niche_aliases, niches, "
            "problem_cluster_members, commercial_signals, "
            "human_decisions, opportunity_scores, creator_scores, "
            "problem_observations, research_runs, audience_interactions, "
            "content_items, creator_platform_accounts, problem_clusters, "
            "evidence, creators CASCADE"
        ))

    async with async_test_session() as session:
        yield session
        await session.rollback()
