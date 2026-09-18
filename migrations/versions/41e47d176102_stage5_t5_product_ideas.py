"""CORP1 Stage 5, T5: product_ideas + product_idea_evidence tables

Revision ID: 41e47d176102
Revises: c64b0f9a5c18
Create Date: 2026-09-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "41e47d176102"
down_revision: str | Sequence[str] | None = "c64b0f9a5c18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Postgres enum values are the Python member *names* (docs/DECISIONS/0001, problem 2).
product_idea_type = sa.Enum(
    "TEMPLATE",
    "CALCULATOR",
    "NOTION_SYSTEM",
    "GUIDE",
    "CHECKLIST",
    "COURSE",
    "APP",
    "TRACKER",
    "DATABASE",
    "MEMBERSHIP",
    "AI_TOOL",
    name="productideatype",
)
product_idea_complexity = sa.Enum("LOW", "MEDIUM", "HIGH", name="productideacomplexity")


def upgrade() -> None:
    # op.create_table auto-creates each enum type from its column
    # definition; do not also call .create() explicitly
    # (docs/DECISIONS/0001, problem 1).
    op.create_table(
        "product_ideas",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("creator_id", sa.String(36), nullable=False),
        sa.Column("problem_cluster_id", sa.String(36), nullable=False),
        sa.Column("research_run_id", sa.String(36), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("idea_type", product_idea_type, nullable=False),
        sa.Column("complexity", product_idea_complexity, nullable=False),
        sa.Column("price_min", sa.Float(), nullable=True),
        sa.Column("price_max", sa.Float(), nullable=True),
        sa.Column("fit_rationale", sa.Text(), nullable=False),
        sa.Column("evidence_terms", sa.JSON(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column(
            "generation_method",
            sa.String(50),
            nullable=False,
            server_default="llm",
        ),
        sa.Column("generation_prompt_version", sa.String(50), nullable=False),
        sa.Column("generation_model_version", sa.String(100), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
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
        sa.CheckConstraint("evidence_count >= 1", name="ck_product_ideas_has_evidence"),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.ForeignKeyConstraint(["problem_cluster_id"], ["problem_clusters.id"]),
        sa.ForeignKeyConstraint(["research_run_id"], ["research_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_ideas_creator_id", "product_ideas", ["creator_id"])
    op.create_index("ix_product_ideas_cluster_id", "product_ideas", ["problem_cluster_id"])
    op.create_index("ix_product_ideas_superseded_at", "product_ideas", ["superseded_at"])

    op.create_table(
        "product_idea_evidence",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("product_idea_id", sa.String(36), nullable=False),
        sa.Column("evidence_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["product_idea_id"], ["product_ideas.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_idea_evidence_unique",
        "product_idea_evidence",
        ["product_idea_id", "evidence_id"],
        unique=True,
    )
    op.create_index(
        "ix_product_idea_evidence_evidence_id", "product_idea_evidence", ["evidence_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_product_idea_evidence_evidence_id", table_name="product_idea_evidence")
    op.drop_index("ix_product_idea_evidence_unique", table_name="product_idea_evidence")
    op.drop_table("product_idea_evidence")

    op.drop_index("ix_product_ideas_superseded_at", table_name="product_ideas")
    op.drop_index("ix_product_ideas_cluster_id", table_name="product_ideas")
    op.drop_index("ix_product_ideas_creator_id", table_name="product_ideas")
    op.drop_table("product_ideas")
    product_idea_complexity.drop(op.get_bind(), checkfirst=True)
    product_idea_type.drop(op.get_bind(), checkfirst=True)
