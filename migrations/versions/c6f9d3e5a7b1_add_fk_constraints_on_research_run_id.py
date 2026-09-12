"""add FK constraints on research_run_id columns

Revision ID: c6f9d3e5a7b1
Revises: b4e7f2a1c3d5
Create Date: 2026-09-12 21:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = "c6f9d3e5a7b1"
down_revision: str | Sequence[str] | None = "b4e7f2a1c3d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_evidence_research_run_id",
        "evidence",
        "research_runs",
        ["research_run_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_creator_scores_research_run_id",
        "creator_scores",
        "research_runs",
        ["research_run_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_opportunity_scores_research_run_id",
        "opportunity_scores",
        "research_runs",
        ["research_run_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_opportunity_scores_research_run_id", "opportunity_scores", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_creator_scores_research_run_id", "creator_scores", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_evidence_research_run_id", "evidence", type_="foreignkey"
    )
