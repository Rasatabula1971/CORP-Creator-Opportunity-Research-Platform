"""phase 3: content_items.extra, score diagnostics

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-13 22:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Adapter metadata worth keeping per content item (commerce signals, tags, music, domain).
    op.add_column(
        "content_items",
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Unweighted per-row diagnostics that explain a score (not part of the hash).
    for table in ("opportunity_scores", "creator_scores"):
        op.add_column(
            table,
            sa.Column("diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )


def downgrade() -> None:
    for table in ("creator_scores", "opportunity_scores"):
        op.drop_column(table, "diagnostics")
    op.drop_column("content_items", "extra")
