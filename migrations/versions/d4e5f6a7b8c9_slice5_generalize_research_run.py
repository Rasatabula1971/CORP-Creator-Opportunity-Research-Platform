"""slice 5: generalize ResearchRun for niche discovery/verification

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-14 17:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_runs", sa.Column("campaign_id", sa.String(36), nullable=True)
    )
    op.add_column("research_runs", sa.Column("niche_id", sa.String(36), nullable=True))
    op.add_column(
        "research_runs",
        sa.Column(
            "run_type",
            sa.String(30),
            nullable=False,
            server_default="creator_research",
        ),
    )
    op.create_foreign_key(
        "fk_research_runs_campaign_id", "research_runs", "campaigns", ["campaign_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_research_runs_niche_id", "research_runs", "niches", ["niche_id"], ["id"]
    )
    op.create_index("ix_runs_campaign_id", "research_runs", ["campaign_id"])
    op.create_index("ix_runs_niche_id", "research_runs", ["niche_id"])
    op.create_index("ix_runs_run_type", "research_runs", ["run_type"])
    # Only the unambiguous half of §11's rules: NICHE_VERIFICATION requires
    # niche_id. CREATOR_RESEARCH is deliberately not constrained to require
    # creator_id — see docs/DECISIONS/0005 and
    # corp/core/state/research_run.py.
    op.create_check_constraint(
        "ck_research_runs_niche_verification_requires_niche",
        "research_runs",
        "run_type != 'niche_verification' OR niche_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_research_runs_niche_verification_requires_niche",
        "research_runs",
        type_="check",
    )
    op.drop_index("ix_runs_run_type", table_name="research_runs")
    op.drop_index("ix_runs_niche_id", table_name="research_runs")
    op.drop_index("ix_runs_campaign_id", table_name="research_runs")
    op.drop_constraint("fk_research_runs_niche_id", "research_runs", type_="foreignkey")
    op.drop_constraint("fk_research_runs_campaign_id", "research_runs", type_="foreignkey")
    op.drop_column("research_runs", "run_type")
    op.drop_column("research_runs", "niche_id")
    op.drop_column("research_runs", "campaign_id")
