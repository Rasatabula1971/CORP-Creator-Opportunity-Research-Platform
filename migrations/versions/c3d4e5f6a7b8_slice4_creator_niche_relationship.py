"""slice 4: creator <-> niche relationship

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-14 16:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creator_niches",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("creator_id", sa.String(36), nullable=False),
        sa.Column("niche_id", sa.String(36), nullable=False),
        sa.Column("discovery_run_id", sa.String(36), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "first_observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.ForeignKeyConstraint(["niche_id"], ["niches.id"]),
        sa.ForeignKeyConstraint(["discovery_run_id"], ["research_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_creator_niches_creator_id", "creator_niches", ["creator_id"])
    op.create_index("ix_creator_niches_niche_id", "creator_niches", ["niche_id"])
    # One creator may belong to many niches and one niche to many creators,
    # but only one association row per (creator, niche) pair — see §14.
    op.create_index(
        "ix_creator_niches_unique_pair",
        "creator_niches",
        ["creator_id", "niche_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_creator_niches_unique_pair", table_name="creator_niches")
    op.drop_index("ix_creator_niches_niche_id", table_name="creator_niches")
    op.drop_index("ix_creator_niches_creator_id", table_name="creator_niches")
    op.drop_table("creator_niches")
