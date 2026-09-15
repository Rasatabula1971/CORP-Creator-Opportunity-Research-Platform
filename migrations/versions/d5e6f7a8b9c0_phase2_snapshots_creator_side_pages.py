"""phase 2: metrics snapshots, creator-side observations, PAGE content type

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-13 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Creator-web pages (Linktree, shop, course, media kit) are content items too.
    op.execute("ALTER TYPE contenttype ADD VALUE IF NOT EXISTS 'PAGE'")

    # Observations now record which side of the creator/audience line they came from.
    op.add_column(
        "problem_observations",
        sa.Column("source_side", sa.String(20), nullable=False, server_default="audience"),
    )
    op.create_index("ix_observations_source_side", "problem_observations", ["source_side"])

    op.create_table(
        "metrics_snapshots",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("research_run_id", sa.String(36), nullable=True),
        sa.Column("platform_account_id", sa.String(36), nullable=True),
        sa.Column("content_item_id", sa.String(36), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("follower_count", sa.Integer(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("share_count", sa.Integer(), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["research_run_id"], ["research_runs.id"]),
        sa.ForeignKeyConstraint(["platform_account_id"], ["creator_platform_accounts.id"]),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_snapshots_account_time", "metrics_snapshots", ["platform_account_id", "captured_at"]
    )
    op.create_index(
        "ix_snapshots_content_time", "metrics_snapshots", ["content_item_id", "captured_at"]
    )
    op.create_index("ix_snapshots_run", "metrics_snapshots", ["research_run_id"])


def downgrade() -> None:
    op.drop_index("ix_snapshots_run", table_name="metrics_snapshots")
    op.drop_index("ix_snapshots_content_time", table_name="metrics_snapshots")
    op.drop_index("ix_snapshots_account_time", table_name="metrics_snapshots")
    op.drop_table("metrics_snapshots")
    op.drop_index("ix_observations_source_side", table_name="problem_observations")
    op.drop_column("problem_observations", "source_side")
    # Postgres cannot drop a value from an enum type; 'PAGE' stays but is unused.
