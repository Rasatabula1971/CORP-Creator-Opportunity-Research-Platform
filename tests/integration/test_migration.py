"""Test that Alembic migrations run clean up and down."""

import subprocess
import os

import pytest


ALEMBIC_CMD = ["alembic"]
ENV = {
    **os.environ,
    "DATABASE_URL_SYNC": "postgresql://corp:corp@localhost:5432/corp_test",
}


def run_alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*ALEMBIC_CMD, *args],
        capture_output=True,
        text=True,
        cwd="/home/user/CORP-Creator-Opportunity-Research-Platform",
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
    assert "head" in result.stdout or "b4e7f2a1c3d5" in result.stdout
