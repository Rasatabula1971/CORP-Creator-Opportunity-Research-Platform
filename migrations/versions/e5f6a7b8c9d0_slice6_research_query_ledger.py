"""slice 6: research query ledger

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-14 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

research_query_status = sa.Enum("SUCCEEDED", "FAILED", name="researchquerystatus")


def upgrade() -> None:
    # op.create_table auto-creates the enum type from the column definition;
    # do not also call .create() explicitly (see docs/DECISIONS/0001, problem 1).
    op.create_table(
        "research_queries",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("research_run_id", sa.String(36), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("results_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_results", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_results", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archive_reference", sa.Text(), nullable=True),
        sa.Column(
            "status", research_query_status, nullable=False, server_default="SUCCEEDED"
        ),
        sa.Column("error", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["research_run_id"], ["research_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_queries_run_id", "research_queries", ["research_run_id"])
    # Lookup by (source, query) is the "has this been searched before?" path.
    # Not unique: the same query is legitimately re-run in later runs, and the
    # history of yields is the point of the ledger.
    op.create_index(
        "ix_research_queries_source_query", "research_queries", ["source", "query"]
    )
    op.create_index("ix_research_queries_executed_at", "research_queries", ["executed_at"])


def downgrade() -> None:
    op.drop_index("ix_research_queries_executed_at", table_name="research_queries")
    op.drop_index("ix_research_queries_source_query", table_name="research_queries")
    op.drop_index("ix_research_queries_run_id", table_name="research_queries")
    op.drop_table("research_queries")
    research_query_status.drop(op.get_bind(), checkfirst=True)
