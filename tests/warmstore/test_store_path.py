"""WarmStore path-safety: never fabricate a missing parent tree."""

import pytest

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
