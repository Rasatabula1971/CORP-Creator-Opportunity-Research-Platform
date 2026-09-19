"""add_active_row_unique_constraints

Ensures at most one active (superseded_at IS NULL) row per natural key
for dossiers, creator_scores, and opportunity_scores.

Revision ID: 15aefe0335b7
Revises: 41e47d176102
Create Date: 2026-09-19 08:27:16.450780

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "15aefe0335b7"
down_revision: str | None = "41e47d176102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_dossiers_active_creator_niche",
        "dossiers",
        ["creator_id", "niche_id"],
        unique=True,
        postgresql_where="superseded_at IS NULL",
    )
    op.create_index(
        "uq_creator_scores_active_creator",
        "creator_scores",
        ["creator_id"],
        unique=True,
        postgresql_where="superseded_at IS NULL",
    )
    op.create_index(
        "uq_opp_scores_active_creator_cluster",
        "opportunity_scores",
        ["creator_id", "problem_cluster_id"],
        unique=True,
        postgresql_where="superseded_at IS NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_opp_scores_active_creator_cluster", table_name="opportunity_scores")
    op.drop_index("uq_creator_scores_active_creator", table_name="creator_scores")
    op.drop_index("uq_dossiers_active_creator_niche", table_name="dossiers")
