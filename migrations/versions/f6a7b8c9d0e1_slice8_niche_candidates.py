"""slice 8: evidence-backed niche candidates

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-15 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Postgres enum values are the Python member *names* (docs/DECISIONS/0001, problem 2).
niche_candidate_status = sa.Enum(
    "STAGED", "PROMOTED", "MERGED", "REJECTED", name="nichecandidatestatus"
)


def upgrade() -> None:
    # op.create_table auto-creates the enum type from the column definition;
    # do not also call .create() explicitly (docs/DECISIONS/0001, problem 1).
    op.create_table(
        "niche_candidates",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("research_run_id", sa.String(36), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("naming_method", sa.String(50), nullable=False),
        sa.Column("naming_terms", sa.JSON(), nullable=True),
        sa.Column("naming_confidence", sa.Float(), nullable=True),
        sa.Column("is_broad_domain", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("author_count", sa.Integer(), nullable=False),
        sa.Column("earliest_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("representative_text", sa.Text(), nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        sa.Column("naming_prompt_version", sa.String(50), nullable=True),
        sa.Column("naming_model_version", sa.String(100), nullable=True),
        sa.Column("status", niche_candidate_status, nullable=False, server_default="STAGED"),
        sa.Column("niche_id", sa.String(36), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
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
        sa.CheckConstraint("evidence_count >= 1", name="ck_niche_candidates_has_evidence"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["research_run_id"], ["research_runs.id"]),
        sa.ForeignKeyConstraint(["niche_id"], ["niches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_niche_candidates_campaign_id", "niche_candidates", ["campaign_id"])
    op.create_index("ix_niche_candidates_run_id", "niche_candidates", ["research_run_id"])
    op.create_index("ix_niche_candidates_status", "niche_candidates", ["status"])
    op.create_index("ix_niche_candidates_superseded_at", "niche_candidates", ["superseded_at"])

    op.create_table(
        "niche_candidate_evidence",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("evidence_id", sa.String(36), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["candidate_id"], ["niche_candidates.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_niche_candidate_evidence_unique",
        "niche_candidate_evidence",
        ["candidate_id", "evidence_id"],
        unique=True,
    )
    op.create_index(
        "ix_niche_candidate_evidence_evidence_id", "niche_candidate_evidence", ["evidence_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_niche_candidate_evidence_evidence_id", table_name="niche_candidate_evidence")
    op.drop_index("ix_niche_candidate_evidence_unique", table_name="niche_candidate_evidence")
    op.drop_table("niche_candidate_evidence")
    op.drop_index("ix_niche_candidates_superseded_at", table_name="niche_candidates")
    op.drop_index("ix_niche_candidates_status", table_name="niche_candidates")
    op.drop_index("ix_niche_candidates_run_id", table_name="niche_candidates")
    op.drop_index("ix_niche_candidates_campaign_id", table_name="niche_candidates")
    op.drop_table("niche_candidates")
    niche_candidate_status.drop(op.get_bind(), checkfirst=True)
