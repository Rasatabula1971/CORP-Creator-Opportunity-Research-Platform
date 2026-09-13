"""add sentiment and urgency to problem observations

Revision ID: f7a4b8c6d2e1
Revises: e5f3a7b2c4d6
Create Date: 2026-09-13 01:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a4b8c6d2e1"
down_revision: str | None = "e5f3a7b2c4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "problem_observations",
        sa.Column("sentiment", sa.String(20), nullable=True),
    )
    op.add_column(
        "problem_observations",
        sa.Column("urgency", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("problem_observations", "urgency")
    op.drop_column("problem_observations", "sentiment")
