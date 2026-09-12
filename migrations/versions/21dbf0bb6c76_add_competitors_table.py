"""add competitors table

Revision ID: 21dbf0bb6c76
Revises: a3b1c9d8e7f6
Create Date: 2026-09-12 19:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "21dbf0bb6c76"
down_revision: str | Sequence[str] | None = "a3b1c9d8e7f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "competitors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("problem_cluster_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "competitor_type",
            sa.Enum("DIRECT", "SUBSTITUTE", "DIY_WORKAROUND", name="competitortype"),
            nullable=False,
        ),
        sa.Column(
            "strength",
            sa.Enum("WEAK", "MODERATE", "STRONG", name="competitorstrength"),
            nullable=False,
        ),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("gap_notes", sa.Text(), nullable=True),
        sa.Column("evidence_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["problem_cluster_id"], ["problem_clusters.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_competitors_cluster_id", "competitors", ["problem_cluster_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_competitors_cluster_id", table_name="competitors")
    op.drop_table("competitors")
    sa.Enum(name="competitortype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="competitorstrength").drop(op.get_bind(), checkfirst=True)
