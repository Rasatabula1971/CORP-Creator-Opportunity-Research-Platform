"""R3: backfill Evidence.evidence_type / origin and make both NOT NULL.

Provenance Invariant (CORP1 spec, frozen) — Stage 4 acceptance: every
Evidence row has both evidence_type and origin set. R1/R2 fixed every code
path; this migration repairs rows written before those fixes and then lets
the database enforce the invariant.

Backfill rules (same source of truth as the code):
* source_type = intent_classification  -> origin INFERENCE, type PROBLEM
* source_type = competitive_analysis   -> origin INFERENCE, type SOLUTION
* everything else                      -> origin OBSERVATION, type from
  corp.core.models.evidence._PLATFORM_EVIDENCE_TYPE by lower(source_platform)

If any row is still NULL after that (an unmapped platform), the migration
raises with the offending platforms rather than guessing.

Revision ID: 5f5732311984
Revises: 0c8be346208b
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from corp.core.models.evidence import _PLATFORM_EVIDENCE_TYPE

revision: str = "5f5732311984"
down_revision: str | Sequence[str] | None = "0c8be346208b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE evidence SET origin = 'INFERENCE', evidence_type = 'PROBLEM' "
        "WHERE source_type = 'intent_classification' "
        "AND (origin IS NULL OR evidence_type IS NULL)"
    )
    op.execute(
        "UPDATE evidence SET origin = 'INFERENCE', evidence_type = 'SOLUTION' "
        "WHERE source_type = 'competitive_analysis' "
        "AND (origin IS NULL OR evidence_type IS NULL)"
    )
    op.execute("UPDATE evidence SET origin = 'OBSERVATION' WHERE origin IS NULL")

    cases = " ".join(
        f"WHEN '{platform}' THEN '{ev_type.name}'::evidencetype"
        for platform, ev_type in sorted(_PLATFORM_EVIDENCE_TYPE.items())
    )
    op.execute(
        "UPDATE evidence SET evidence_type = CASE lower(source_platform) "
        f"{cases} END WHERE evidence_type IS NULL"
    )

    bind = op.get_bind()
    leftover = bind.execute(
        sa.text(
            "SELECT DISTINCT source_platform FROM evidence "
            "WHERE evidence_type IS NULL OR origin IS NULL"
        )
    ).scalars().all()
    if leftover:
        raise RuntimeError(
            "R3 backfill left rows without provenance for platforms "
            f"{sorted(leftover)}; add them to _PLATFORM_EVIDENCE_TYPE and re-run"
        )

    op.alter_column("evidence", "evidence_type", nullable=False)
    op.alter_column("evidence", "origin", nullable=False)


def downgrade() -> None:
    op.alter_column("evidence", "origin", nullable=True)
    op.alter_column("evidence", "evidence_type", nullable=True)
