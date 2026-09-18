"""CORP1 Stage 4 baseline: niche/candidate drill-down tree, evidence_type,
research_more decision, and the new dossiers table (T0)

Revision ID: c64b0f9a5c18
Revises: 6c88964d1240
Create Date: 2026-09-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c64b0f9a5c18"
down_revision: str | Sequence[str] | None = "6c88964d1240"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Postgres enum values are the Python member *names* (docs/DECISIONS/0001, problem 2).
dossier_status = sa.Enum(
    "PENDING_REVIEW",
    "APPROVED",
    "REJECTED",
    "WATCHING",
    "RESEARCH_MORE_IN_PROGRESS",
    name="dossierstatus",
)
evidence_type = sa.Enum(
    "PROBLEM",
    "SEARCH_INTENT",
    "TREND",
    "PLANNING_INTENT",
    "TRANSACTION",
    "SOLUTION",
    "MONETISATION",
    "DISSATISFACTION",
    name="evidencetype",
)


def upgrade() -> None:
    # ---- Niche drill-down tree ----
    op.add_column("niches", sa.Column("parent_niche_id", sa.String(36), nullable=True))
    op.add_column(
        "niches",
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_foreign_key(
        "fk_niches_parent_niche_id", "niches", "niches", ["parent_niche_id"], ["id"]
    )
    op.create_index("ix_niches_parent_niche_id", "niches", ["parent_niche_id"])

    # ---- NicheCandidate drill-down tree + DRILLING status ----
    op.add_column(
        "niche_candidates", sa.Column("parent_candidate_id", sa.String(36), nullable=True)
    )
    op.add_column(
        "niche_candidates",
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_foreign_key(
        "fk_niche_candidates_parent_candidate_id",
        "niche_candidates",
        "niche_candidates",
        ["parent_candidate_id"],
        ["id"],
    )
    op.create_index(
        "ix_niche_candidates_parent_candidate_id", "niche_candidates", ["parent_candidate_id"]
    )
    op.execute("ALTER TYPE nichecandidatestatus ADD VALUE IF NOT EXISTS 'DRILLING'")

    # ---- Evidence: capability-provider classification ----
    # New enum type; column is nullable so pre-Stage-4 evidence rows are
    # unaffected. Unlike op.create_table (docs/DECISIONS/0001, problem 1),
    # op.add_column does NOT auto-create the enum type, so it is created
    # explicitly here.
    evidence_type.create(op.get_bind(), checkfirst=True)
    op.add_column("evidence", sa.Column("evidence_type", evidence_type, nullable=True))

    # ---- HumanDecision: RESEARCH_MORE + dossier_id ----
    op.execute("ALTER TYPE decisiontype ADD VALUE IF NOT EXISTS 'RESEARCH_MORE'")
    op.add_column("human_decisions", sa.Column("dossier_id", sa.String(36), nullable=True))
    op.create_index("ix_decisions_dossier_id", "human_decisions", ["dossier_id"])

    # ---- New: dossiers + dossier_evidence ----
    op.create_table(
        "dossiers",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("creator_id", sa.String(36), nullable=False),
        sa.Column("niche_id", sa.String(36), nullable=False),
        sa.Column("opportunity_score_id", sa.String(36), nullable=False),
        sa.Column("research_run_id", sa.String(36), nullable=True),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", dossier_status, nullable=False, server_default="PENDING_REVIEW"),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.ForeignKeyConstraint(["niche_id"], ["niches.id"]),
        sa.ForeignKeyConstraint(["opportunity_score_id"], ["opportunity_scores.id"]),
        sa.ForeignKeyConstraint(["research_run_id"], ["research_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dossiers_creator_id", "dossiers", ["creator_id"])
    op.create_index("ix_dossiers_niche_id", "dossiers", ["niche_id"])
    op.create_index("ix_dossiers_status", "dossiers", ["status"])
    op.create_index("ix_dossiers_superseded_at", "dossiers", ["superseded_at"])

    # Now that dossiers exists, wire human_decisions.dossier_id to it.
    op.create_foreign_key(
        "fk_human_decisions_dossier_id", "human_decisions", "dossiers", ["dossier_id"], ["id"]
    )

    op.create_table(
        "dossier_evidence",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("dossier_id", sa.String(36), nullable=False),
        sa.Column("evidence_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["dossier_id"], ["dossiers.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dossier_evidence_unique",
        "dossier_evidence",
        ["dossier_id", "evidence_id"],
        unique=True,
    )
    op.create_index("ix_dossier_evidence_evidence_id", "dossier_evidence", ["evidence_id"])


def downgrade() -> None:
    op.drop_index("ix_dossier_evidence_evidence_id", table_name="dossier_evidence")
    op.drop_index("ix_dossier_evidence_unique", table_name="dossier_evidence")
    op.drop_table("dossier_evidence")

    op.drop_constraint("fk_human_decisions_dossier_id", "human_decisions", type_="foreignkey")
    op.drop_index("ix_dossiers_superseded_at", table_name="dossiers")
    op.drop_index("ix_dossiers_status", table_name="dossiers")
    op.drop_index("ix_dossiers_niche_id", table_name="dossiers")
    op.drop_index("ix_dossiers_creator_id", table_name="dossiers")
    op.drop_table("dossiers")
    dossier_status.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_decisions_dossier_id", table_name="human_decisions")
    op.drop_column("human_decisions", "dossier_id")
    # Postgres cannot drop a value from an enum type; RESEARCH_MORE and
    # DRILLING stay defined but unused after downgrade.

    op.drop_column("evidence", "evidence_type")
    evidence_type.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_niche_candidates_parent_candidate_id", table_name="niche_candidates")
    op.drop_constraint(
        "fk_niche_candidates_parent_candidate_id", "niche_candidates", type_="foreignkey"
    )
    op.drop_column("niche_candidates", "depth")
    op.drop_column("niche_candidates", "parent_candidate_id")

    op.drop_index("ix_niches_parent_niche_id", table_name="niches")
    op.drop_constraint("fk_niches_parent_niche_id", "niches", type_="foreignkey")
    op.drop_column("niches", "depth")
    op.drop_column("niches", "parent_niche_id")
