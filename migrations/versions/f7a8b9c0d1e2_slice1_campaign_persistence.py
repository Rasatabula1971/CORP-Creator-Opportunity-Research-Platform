"""slice 1: campaign persistence

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-14 13:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: str | Sequence[str] | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

campaign_status = sa.Enum(
    "DRAFT", "ACTIVE", "PAUSED", "COMPLETED", name="campaignstatus"
)


def upgrade() -> None:
    # op.create_table auto-creates the enum type from the column definition;
    # creating it explicitly here as well would double-create it.
    op.create_table(
        "campaigns",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "status",
            campaign_status,
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("research_profile_version", sa.String(50), nullable=True),
        sa.Column(
            "target_niche_count", sa.Integer(), nullable=False, server_default="10"
        ),
        sa.Column(
            "initial_creators_per_niche", sa.Integer(), nullable=False, server_default="10"
        ),
        sa.Column(
            "creator_min_followers", sa.Integer(), nullable=False, server_default="10000"
        ),
        sa.Column(
            "creator_max_followers", sa.Integer(), nullable=False, server_default="200000"
        ),
        sa.Column(
            "human_gate_capacity", sa.Integer(), nullable=False, server_default="50"
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaigns_status", "campaigns", ["status"])


def downgrade() -> None:
    op.drop_index("ix_campaigns_status", table_name="campaigns")
    op.drop_table("campaigns")
    campaign_status.drop(op.get_bind(), checkfirst=True)
