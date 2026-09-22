"""make research_run creator_id nullable

Revision ID: b4e7f2a1c3d5
Revises: 21dbf0bb6c76
Create Date: 2026-09-12 20:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4e7f2a1c3d5"
down_revision: str | Sequence[str] | None = "21dbf0bb6c76"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "research_runs",
        "creator_id",
        existing_type=sa.String(36),
        nullable=True,
    )


def downgrade() -> None:
    # Rows with NULL creator_id (cross-creator / niche-discovery runs) cannot
    # exist under the old NOT NULL schema, and pointing them at a fabricated
    # 'unknown' id violates the FK to creators.id. Delete them — a downgrade
    # to the pre-niche schema has no way to represent these runs. (Later
    # tables referencing research_runs are already gone by this point in the
    # downgrade chain, and the evidence FK is dropped one revision earlier.)
    op.execute("DELETE FROM research_runs WHERE creator_id IS NULL")
    op.alter_column(
        "research_runs",
        "creator_id",
        existing_type=sa.String(36),
        nullable=False,
    )
