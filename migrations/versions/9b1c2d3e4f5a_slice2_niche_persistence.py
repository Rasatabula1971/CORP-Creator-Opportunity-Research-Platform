"""slice 2: canonical niche persistence

Revision ID: a1b2c3d4e5f6
Revises: f7a8b9c0d1e2
Create Date: 2026-09-14 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9b1c2d3e4f5a"
down_revision: str | Sequence[str] | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

niche_policy_class = sa.Enum(
    "STANDARD", "RESTRICTED", "EXCLUDED", name="nichepolicyclass"
)
niche_lifecycle_status = sa.Enum(
    "CANDIDATE", "ACTIVE", "EXPAND", "COOLDOWN", "RECHECK_DUE", name="nichelifecyclestatus"
)


def upgrade() -> None:
    # op.create_table auto-creates enum types from column definitions; do not
    # also call .create() explicitly (see docs/DECISIONS/0001, problem 1).
    op.create_table(
        "niches",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("parent_domain", sa.String(255), nullable=True),
        sa.Column(
            "policy_class", niche_policy_class, nullable=False, server_default="STANDARD"
        ),
        sa.Column(
            "lifecycle_status",
            niche_lifecycle_status,
            nullable=False,
            server_default="CANDIDATE",
        ),
        sa.Column(
            "first_discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_researched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_recheck_at", sa.DateTime(timezone=True), nullable=True),
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
    # Case-insensitive: "DIY Performance Tuning" and "diy performance tuning"
    # must be the same canonical niche.
    op.create_index(
        "ix_niches_canonical_name_ci",
        "niches",
        [sa.text("lower(canonical_name)")],
        unique=True,
    )
    op.create_index("ix_niches_lifecycle_status", "niches", ["lifecycle_status"])
    op.create_index("ix_niches_policy_class", "niches", ["policy_class"])

    op.create_table(
        "niche_aliases",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("niche_id", sa.String(36), nullable=False),
        sa.Column("alias", sa.String(255), nullable=False),
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
        sa.ForeignKeyConstraint(["niche_id"], ["niches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_niche_aliases_niche_id", "niche_aliases", ["niche_id"])
    # Case-insensitive, global: one alias string resolves to exactly one niche.
    op.create_index(
        "ix_niche_aliases_alias_ci", "niche_aliases", [sa.text("lower(alias)")], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_niche_aliases_alias_ci", table_name="niche_aliases")
    op.drop_index("ix_niche_aliases_niche_id", table_name="niche_aliases")
    op.drop_table("niche_aliases")

    op.drop_index("ix_niches_policy_class", table_name="niches")
    op.drop_index("ix_niches_lifecycle_status", table_name="niches")
    op.drop_index("ix_niches_canonical_name_ci", table_name="niches")
    op.drop_table("niches")

    niche_lifecycle_status.drop(op.get_bind(), checkfirst=True)
    niche_policy_class.drop(op.get_bind(), checkfirst=True)
