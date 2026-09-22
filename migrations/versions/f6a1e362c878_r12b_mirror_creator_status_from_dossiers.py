"""R12b: backfill Creator.status from active dossier decisions.

Before R12b the dossier decision gate set Dossier.status only, leaving the
creator at HUMAN_REVIEW after every dossier had been watched, approved or
rejected. Apply the same precedence the code now uses
(corp.core.state.gates.creator_status_for_dossiers) to creators currently
at HUMAN_REVIEW: any approved active dossier → APPROVED; else if any is
still pending/in progress → stay; else any watching → WATCHING; else all
rejected → REJECTED. Only HUMAN_REVIEW creators are touched, and only via
moves the state machine allows from that state.

Revision ID: f6a1e362c878
Revises: adc83dc5b00e
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f6a1e362c878"
down_revision: str | Sequence[str] | None = "adc83dc5b00e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE creators AS c
        SET status = CASE
            WHEN EXISTS (SELECT 1 FROM dossiers d WHERE d.creator_id = c.id
                         AND d.superseded_at IS NULL AND d.status = 'APPROVED')
                THEN 'APPROVED'::creatorstatus
            WHEN EXISTS (SELECT 1 FROM dossiers d WHERE d.creator_id = c.id
                         AND d.superseded_at IS NULL
                         AND d.status IN ('PENDING_REVIEW', 'RESEARCH_MORE_IN_PROGRESS'))
                THEN c.status
            WHEN EXISTS (SELECT 1 FROM dossiers d WHERE d.creator_id = c.id
                         AND d.superseded_at IS NULL AND d.status = 'WATCHING')
                THEN 'WATCHING'::creatorstatus
            ELSE 'REJECTED'::creatorstatus
        END
        WHERE c.status = 'HUMAN_REVIEW'
          AND EXISTS (SELECT 1 FROM dossiers d
                      WHERE d.creator_id = c.id AND d.superseded_at IS NULL)
        """
    )


def downgrade() -> None:
    # The pre-R12b state was "creator stays HUMAN_REVIEW after a dossier
    # decision"; restore that for creators whose only gate history is via
    # dossiers (HumanDecision rows at GATE_D), leaving Gate A outcomes alone.
    op.execute(
        """
        UPDATE creators AS c
        SET status = 'HUMAN_REVIEW'::creatorstatus
        WHERE c.status IN ('WATCHING', 'APPROVED', 'REJECTED')
          AND EXISTS (SELECT 1 FROM dossiers d
                      WHERE d.creator_id = c.id AND d.superseded_at IS NULL)
          AND NOT EXISTS (SELECT 1 FROM human_decisions h
                          WHERE h.creator_id = c.id AND h.gate = 'GATE_A')
        """
    )
