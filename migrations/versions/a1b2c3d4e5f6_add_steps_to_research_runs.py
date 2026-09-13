"""add steps column to research_runs

Revision ID: a1b2c3d4e5f6
Revises: f7a4b8c6d2e1
Create Date: 2026-09-13 02:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f7a4b8c6d2e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_runs",
        sa.Column("steps", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("research_runs", "steps")
