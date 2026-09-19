"""Add unique partial index on niche_candidates for dedup.

Stage 4 acceptance test #3: no two NicheCandidate rows for the same
(parent, depth, canonical name) within an active registry window
(superseded_at IS NULL).

Revision ID: 0c8be346208b
Revises: a7b8c9d0e1f2
Create Date: 2026-09-19

"""

from alembic import op

revision = "0c8be346208b"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_niche_candidates_active_parent_depth_label "
        "ON niche_candidates (parent_candidate_id, depth, lower(label)) "
        "WHERE superseded_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index(
        "uq_niche_candidates_active_parent_depth_label",
        table_name="niche_candidates",
    )
