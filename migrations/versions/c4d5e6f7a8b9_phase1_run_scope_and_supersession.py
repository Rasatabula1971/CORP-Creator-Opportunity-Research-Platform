"""phase 1: run scope + stats, cluster creator scoping, supersession markers

Revision ID: c4d5e6f7a8b9
Revises: a3b1c9d8e7f6
Create Date: 2026-09-13 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Research runs may be niche- or cross-creator scoped. creator_id is already
    # nullable (b4e7f2a1c3d5 owns that change); this revision only adds scope/stats.
    op.add_column(
        "research_runs",
        sa.Column("scope", sa.String(20), nullable=False, server_default="creator"),
    )
    op.add_column(
        "research_runs",
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # Clusters know which creator they were built for; old rows are superseded, never deleted.
    op.add_column("problem_clusters", sa.Column("creator_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_problem_clusters_creator", "problem_clusters", "creators", ["creator_id"], ["id"]
    )
    op.create_index("ix_clusters_creator_id", "problem_clusters", ["creator_id"])
    op.add_column(
        "problem_clusters", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True)
    )

    for table in ("opportunity_scores", "creator_scores", "commercial_signals"):
        op.add_column(
            table, sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.create_index(f"ix_{table}_active", table, ["superseded_at"])


def downgrade() -> None:
    for table in ("commercial_signals", "creator_scores", "opportunity_scores"):
        op.drop_index(f"ix_{table}_active", table_name=table)
        op.drop_column(table, "superseded_at")

    op.drop_column("problem_clusters", "superseded_at")
    op.drop_index("ix_clusters_creator_id", table_name="problem_clusters")
    op.drop_constraint("fk_problem_clusters_creator", "problem_clusters", type_="foreignkey")
    op.drop_column("problem_clusters", "creator_id")

    op.drop_column("research_runs", "stats")
    op.drop_column("research_runs", "scope")
    # Do NOT touch creator_id nullability here. At this point in the chain the
    # research_run_id FKs from c6f9d3e5a7b1 still exist, so deleting NULL-creator
    # runs (niche-discovery / cross-creator) would violate fk_evidence_research_run_id.
    # b4e7f2a1c3d5.downgrade() restores NOT NULL after those FKs are dropped.
