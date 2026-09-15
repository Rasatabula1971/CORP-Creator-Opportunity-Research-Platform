"""Maintenance ops — prune bulk history from Postgres to keep it bounded.

The warm store (SQLite on external storage) mirrors bulk rows via the pipeline's
dual-write, so history that Postgres no longer needs for reads or referential
integrity can be dropped from the primary database while the full record lives on.

Only ``metrics_snapshots`` is pruned today, and deliberately so:

* It is append-only *history*; the latest counts are denormalized onto
  ``ContentItem`` / ``CreatorPlatformAccount``, so dropping old rows loses nothing
  the app reads back.
* It is a leaf table — nothing has a foreign key to it — so deletes can't cascade.
* The API never reads it.
* It is mirrored to the warm store (``mirror_metrics``).

What is NOT pruned, and why: ``evidence`` and ``problem_observations`` are read by
the dashboard and referenced by ``problem_clusters`` / ``opportunity_scores`` /
``commercial_intent_signals`` / ``niche_candidate_evidence`` — deleting them would
remove research *results*, not just bulk. ``audience_interactions`` is a leaf and
not API-read, but it has no row-creation timestamp (only ``posted_at``), so it
can't be pruned by collection age safely; left for a follow-up that adds one.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.metrics import MetricsSnapshot

DEFAULT_RETENTION_DAYS = 90


@dataclass
class PruneReport:
    retention_days: int
    cutoff: str
    applied: bool
    metrics_snapshots: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class PruneService:
    """Deletes safe-to-drop bulk history older than a retention window.

    Dry-run by default: :meth:`prune` with ``apply=False`` only counts what would
    be removed. The caller commits when ``apply=True``.
    """

    def __init__(self, session: AsyncSession, retention_days: int = DEFAULT_RETENTION_DAYS) -> None:
        if retention_days < 0:
            raise ValueError("retention_days must be >= 0")
        self._session = session
        self._retention_days = retention_days

    async def prune(self, *, apply: bool = False) -> PruneReport:
        cutoff = datetime.now(UTC) - timedelta(days=self._retention_days)

        count = await self._session.scalar(
            select(func.count())
            .select_from(MetricsSnapshot)
            .where(MetricsSnapshot.captured_at < cutoff)
        )
        count = int(count or 0)

        if apply and count:
            await self._session.execute(
                delete(MetricsSnapshot).where(MetricsSnapshot.captured_at < cutoff)
            )

        return PruneReport(
            retention_days=self._retention_days,
            cutoff=cutoff.isoformat(),
            applied=apply,
            metrics_snapshots=count,
        )
