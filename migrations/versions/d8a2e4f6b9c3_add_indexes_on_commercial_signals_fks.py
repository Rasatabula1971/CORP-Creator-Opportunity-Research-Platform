"""Add indexes on commercial_signals FK columns.

Revision ID: d8a2e4f6b9c3
Revises: c6f9d3e5a7b1
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d8a2e4f6b9c3"
down_revision: str = "c6f9d3e5a7b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_signals_cluster_id", "commercial_signals", ["problem_cluster_id"])
    op.create_index("ix_signals_evidence_id", "commercial_signals", ["evidence_id"])


def downgrade() -> None:
    op.drop_index("ix_signals_evidence_id", table_name="commercial_signals")
    op.drop_index("ix_signals_cluster_id", table_name="commercial_signals")
