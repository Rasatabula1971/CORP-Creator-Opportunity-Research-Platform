"""Test that Alembic migrations run clean up and down."""

import os
import subprocess
from pathlib import Path

ALEMBIC_CMD = ["alembic"]
ENV = {
    **os.environ,
    "DATABASE_URL_SYNC": "postgresql://corp:corp@localhost:5432/corp_test",
}

# Repo root = two levels up from tests/integration/. Deriving it avoids a
# hardcoded absolute path whose casing broke on case-sensitive filesystems.
REPO_ROOT = Path(__file__).resolve().parents[2]


def run_alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*ALEMBIC_CMD, *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=ENV,
    )


def test_migration_downgrade_upgrade():
    """Verify migration can go down to base and back up cleanly."""
    result = run_alembic("downgrade", "base")
    assert result.returncode == 0, f"Downgrade failed: {result.stderr}"

    result = run_alembic("upgrade", "head")
    assert result.returncode == 0, f"Upgrade failed: {result.stderr}"


def test_migration_current_is_head():
    result = run_alembic("current")
    assert result.returncode == 0
    assert "head" in result.stdout or "d8a2e4f6b9c3" in result.stdout
