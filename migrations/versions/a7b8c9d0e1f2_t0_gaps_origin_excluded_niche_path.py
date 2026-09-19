"""T0 spec gaps: Evidence.origin enum, NicheLifecycleStatus.EXCLUDED,
Dossier.niche_path

Revision ID: a7b8c9d0e1f2
Revises: 15aefe0335b7
Create Date: 2026-09-19 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "15aefe0335b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

evidence_origin = sa.Enum("OBSERVATION", "INFERENCE", name="evidenceorigin")


def upgrade() -> None:
    # ---- Evidence.origin: observation vs inference (Provenance Invariant) ----
    evidence_origin.create(op.get_bind(), checkfirst=True)
    op.add_column("evidence", sa.Column("origin", evidence_origin, nullable=True))

    # ---- NicheLifecycleStatus: add EXCLUDED ----
    op.execute(
        "ALTER TYPE nichelifecyclestatus ADD VALUE IF NOT EXISTS 'EXCLUDED'"
    )

    # ---- Dossier.niche_path: persisted drill-down path for CORP2 handoff ----
    op.add_column(
        "dossiers",
        sa.Column("niche_path", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dossiers", "niche_path")
    # Postgres cannot drop an enum value; EXCLUDED stays defined but unused.
    op.drop_column("evidence", "origin")
    evidence_origin.drop(op.get_bind(), checkfirst=True)
