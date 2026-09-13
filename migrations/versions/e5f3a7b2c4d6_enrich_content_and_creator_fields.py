"""enrich content and creator fields

Revision ID: e5f3a7b2c4d6
Revises: d8a2e4f6b9c3
Create Date: 2026-09-13 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f3a7b2c4d6"
down_revision: str | None = "d8a2e4f6b9c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ContentItem: video metadata fields
    op.add_column("content_items", sa.Column("duration", sa.Integer(), nullable=True))
    op.add_column(
        "content_items",
        sa.Column("tags", sa.dialects.postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "content_items", sa.Column("language", sa.String(10), nullable=True)
    )
    op.add_column(
        "content_items", sa.Column("is_short", sa.Boolean(), nullable=True)
    )

    # AudienceInteraction: commenter channel ID
    op.add_column(
        "audience_interactions",
        sa.Column("author_channel_id", sa.String(255), nullable=True),
    )

    # CreatorPlatformAccount: channel-level stats
    op.add_column(
        "creator_platform_accounts",
        sa.Column("total_view_count", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "creator_platform_accounts",
        sa.Column("video_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "creator_platform_accounts",
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "creator_platform_accounts",
        sa.Column("country", sa.String(10), nullable=True),
    )
    op.add_column(
        "creator_platform_accounts",
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("creator_platform_accounts", "description")
    op.drop_column("creator_platform_accounts", "country")
    op.drop_column("creator_platform_accounts", "joined_at")
    op.drop_column("creator_platform_accounts", "video_count")
    op.drop_column("creator_platform_accounts", "total_view_count")
    op.drop_column("audience_interactions", "author_channel_id")
    op.drop_column("content_items", "is_short")
    op.drop_column("content_items", "language")
    op.drop_column("content_items", "tags")
    op.drop_column("content_items", "duration")
