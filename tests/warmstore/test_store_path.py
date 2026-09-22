"""WarmStore path-safety: never fabricate a missing parent tree."""

import pytest
from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy.ext.asyncio import create_async_engine

from corp.warmstore.store import WarmStore


async def test_init_creates_db_dir_when_parent_exists(tmp_path):
    # tmp_path exists; the DB's own subdir does not yet.
    db_path = tmp_path / "corp_data" / "warm.db"
    store = WarmStore(db_path)
    try:
        await store.init_db()
        assert db_path.parent.is_dir()
    finally:
        await store.close()


async def test_init_refuses_when_parent_tree_missing(tmp_path):
    # Simulate an unmounted external drive: the grandparent dir does not exist.
    db_path = tmp_path / "unmounted_drive" / "corp_data" / "warm.db"
    store = WarmStore(db_path)
    try:
        with pytest.raises(FileNotFoundError):
            await store.init_db()
        # Crucially, we did NOT fabricate the missing tree on the root filesystem.
        assert not (tmp_path / "unmounted_drive").exists()
    finally:
        await store.close()


async def test_init_heals_missing_columns_on_an_existing_file(tmp_path):
    """A warm.db predating a schema.py column addition must self-heal, not
    crash forever — this is the scenario a stale mirror on an existing
    deployment (or laptop) actually hits after pulling a model change."""
    db_path = tmp_path / "warm.db"

    # Simulate the "old" on-disk schema: create problem_observations without
    # the columns a later schema.py version added.
    old_metadata = MetaData()
    Table(
        "problem_observations",
        old_metadata,
        Column("id", String(36), primary_key=True),
        Column("evidence_id", String(36), nullable=False),
        Column("text", String, nullable=False),
    )
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(old_metadata.create_all)
    await engine.dispose()

    store = WarmStore(db_path)
    try:
        await store.init_db()  # must not raise, and must add the new columns
        count = await store.put_observations([
            {
                "id": "obs-1",
                "evidence_id": "ev-1",
                "text": "t",
                "category": None,
                "is_inferred": 0,
                "extraction_prompt_version": "extract_v3",
                "model_version": "m",
                "confidence": 0.5,
                "source_side": "audience",
                "sentiment": "negative",
                "urgency": "low",
                "embedding": None,
                "created_at": None,
                "updated_at": None,
            }
        ])
        assert count == 1
    finally:
        await store.close()
