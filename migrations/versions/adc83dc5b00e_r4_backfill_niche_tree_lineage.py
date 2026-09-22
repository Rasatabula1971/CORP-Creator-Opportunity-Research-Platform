"""R4: backfill Niche.parent_niche_id / depth from promoted candidates.

Canonicalization never carried NicheCandidate.parent_candidate_id / depth
onto the Niche it created, so every niche sat at depth 0 with no parent and
the drill-down path in dossiers and the CORP2 handoff was one node. Going
forward canonicalization sets both (ADR-0052); this repairs existing rows
where the lineage is still recoverable: a niche whose PROMOTED candidate has
a parent candidate that itself resolved to a niche.

Only niches with no parent yet are touched; a niche is never re-parented
and never made its own parent.

Revision ID: adc83dc5b00e
Revises: 5f5732311984
Create Date: 2026-09-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "adc83dc5b00e"
down_revision: str | Sequence[str] | None = "5f5732311984"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE niches AS n
        SET parent_niche_id = pn.id,
            depth = pn.depth + 1
        FROM niche_candidates AS c
        JOIN niche_candidates AS p ON p.id = c.parent_candidate_id
        JOIN niches AS pn ON pn.id = p.niche_id
        WHERE c.niche_id = n.id
          AND c.status = 'PROMOTED'
          AND pn.id <> n.id
          AND n.parent_niche_id IS NULL
        """
    )


def downgrade() -> None:
    # Lineage is derived data. Pre-R4 every niche was a depth-0 root, so
    # clearing ALL lineage -- including rows the canonicalizer wrote after
    # this upgrade -- restores exactly that state.
    op.execute("UPDATE niches SET parent_niche_id = NULL, depth = 0")
