"""make research_run creator_id nullable

Revision ID: b4e7f2a1c3d5
Revises: 21dbf0bb6c76
Create Date: 2026-09-12 20:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

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
    op.execute("UPDATE research_runs SET creator_id = 'unknown' WHERE creator_id IS NULL")
    op.alter_column(
        "research_runs",
        "creator_id",
        existing_type=sa.String(36),
        nullable=False,
    )
