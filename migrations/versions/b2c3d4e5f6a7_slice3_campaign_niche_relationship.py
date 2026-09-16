"""slice 3: campaign <-> niche relationship

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-14 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "9b1c2d3e4f5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

campaign_niche_status = sa.Enum(
    "DISCOVERED", "VERIFIED", "SELECTED", "REJECTED", name="campaignnichestatus"
)


def upgrade() -> None:
    # op.create_table auto-creates the enum type from the column definition;
    # do not also call .create() explicitly (see docs/DECISIONS/0001, problem 1).
    op.create_table(
        "campaign_niches",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("niche_id", sa.String(36), nullable=False),
        sa.Column("discovery_rank", sa.Integer(), nullable=True),
        sa.Column("qualification_score", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("research_completeness", sa.Float(), nullable=True),
        sa.Column(
            "creator_count_observed", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("target_band_creator_count", sa.Integer(), nullable=True),
        sa.Column(
            "status", campaign_niche_status, nullable=False, server_default="DISCOVERED"
        ),
        sa.Column(
            "selected", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["niche_id"], ["niches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_campaign_niches_campaign_id", "campaign_niches", ["campaign_id"]
    )
    op.create_index("ix_campaign_niches_niche_id", "campaign_niches", ["niche_id"])
    # Same niche may appear in many campaigns, but only once per campaign.
    op.create_index(
        "ix_campaign_niches_unique_pair",
        "campaign_niches",
        ["campaign_id", "niche_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_campaign_niches_unique_pair", table_name="campaign_niches")
    op.drop_index("ix_campaign_niches_niche_id", table_name="campaign_niches")
    op.drop_index("ix_campaign_niches_campaign_id", table_name="campaign_niches")
    op.drop_table("campaign_niches")
    campaign_niche_status.drop(op.get_bind(), checkfirst=True)
