"""Creator-first discovery, step 1: audience problem clusters → micro-niche
suggestions awaiting approval.

A creator in the 10K–200K band is proof that an audience exists and keeps
coming back. What that audience *struggles with* — the ProblemClusters the
intelligence pipeline already builds from their comments — is a sharper
niche than the creator's own label: not "woodworking" but "finishing
outdoor oak". This module turns those clusters into rows in the
micro-niche approval queue. It never drills anything itself.

**No spend.** Everything here is a database read. The LLM cost of a
micro-niche is paid only when a human approves it and the drill engine
runs, which is the point of approval-first.

**What is left out, and why:**

* Clusters below ``min_frequency`` observations — one person's complaint
  is an anecdote, not a niche.
* Clusters from creators whose known follower count is outside the band.
  An unknown count is let through (flagged by ``follower_count`` = None):
  it cannot be shown to be out of band, and hand-added creators often have
  none recorded.
* Archived creators.
* Anything matching the Stage 3 exclusion rules — the spec says excluded
  niches are never surfaced for review, and that check is deterministic.
* Labels whose niche is still inside its 90-day research window.
* Labels a human already decided on. A rejection sticks; otherwise the
  queue never shrinks.

**One suggestion per label, one source per creator.** The same problem in
three creators' audiences is one suggestion with three sources — the
strongest evidence the queue can show. Re-researching a creator supersedes
their clusters and makes new ones; keying sources by creator (not cluster)
means that refreshes a source instead of double-counting it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import Creator, CreatorPlatformAccount
from corp.core.models.intelligence import ProblemCluster
from corp.core.models.micro_niche import MicroNicheStatus, MicroNicheSuggestion
from corp.workers.intelligence.niche_discovery import (
    DiscoveryConfig,
    matched_exclusion,
    registry_fresh,
)

logger = logging.getLogger(__name__)

DEFAULT_MIN_FREQUENCY = 3
DEFAULT_MIN_FOLLOWERS = 10_000
DEFAULT_MAX_FOLLOWERS = 200_000


def normalize_label(label: str) -> str:
    return " ".join(label.lower().split())


@dataclass
class SuggestionStats:
    clusters_seen: int = 0
    created: int = 0
    updated: int = 0
    skipped_low_frequency: int = 0
    skipped_out_of_band: int = 0
    skipped_excluded: int = 0
    skipped_registry_fresh: int = 0
    skipped_already_decided: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "clusters_seen": self.clusters_seen,
            "created": self.created,
            "updated": self.updated,
            "skipped_low_frequency": self.skipped_low_frequency,
            "skipped_out_of_band": self.skipped_out_of_band,
            "skipped_excluded": self.skipped_excluded,
            "skipped_registry_fresh": self.skipped_registry_fresh,
            "skipped_already_decided": self.skipped_already_decided,
        }


@dataclass(frozen=True, slots=True)
class _Source:
    cluster_id: str
    creator_id: str
    label: str
    frequency: int
    creator_niche: str | None
    follower_count: int | None

    def as_json(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "creator_id": self.creator_id,
            "label": self.label,
            "frequency": self.frequency,
        }


class MicroNicheSeeder:
    def __init__(
        self,
        session: AsyncSession,
        *,
        min_frequency: int = DEFAULT_MIN_FREQUENCY,
        min_followers: int = DEFAULT_MIN_FOLLOWERS,
        max_followers: int = DEFAULT_MAX_FOLLOWERS,
        discovery_config: DiscoveryConfig | None = None,
        niche_rules_path: str = "rules/niche_discovery_prompt.yaml",
    ) -> None:
        self._session = session
        self._min_frequency = min_frequency
        self._min_followers = min_followers
        self._max_followers = max_followers
        # The Stage 3 exclusion list lives in the drill engine's rules; read
        # it from there so there is one frozen copy.
        self._discovery = discovery_config or DiscoveryConfig.from_rules(niche_rules_path)

    async def suggest(self, creator_id: str | None = None) -> SuggestionStats:
        """Refresh the queue from active clusters (one creator's, or all).

        Caller owns the transaction.
        """
        stats = SuggestionStats()
        followers = (
            select(
                CreatorPlatformAccount.creator_id.label("creator_id"),
                func.max(CreatorPlatformAccount.subscriber_count).label("followers"),
            )
            .group_by(CreatorPlatformAccount.creator_id)
            .subquery()
        )
        query = (
            select(ProblemCluster, Creator.niche, followers.c.followers)
            .join(Creator, Creator.id == ProblemCluster.creator_id)
            .outerjoin(followers, followers.c.creator_id == Creator.id)
            .where(
                ProblemCluster.superseded_at.is_(None),
                ProblemCluster.creator_id.isnot(None),
                Creator.archived_at.is_(None),
            )
        )
        if creator_id is not None:
            query = query.where(ProblemCluster.creator_id == creator_id)

        # normalised label → creator_id → strongest source for that pair
        grouped: dict[str, dict[str, _Source]] = {}
        display: dict[str, str] = {}
        for cluster, creator_niche, follower_count in (await self._session.execute(query)).all():
            stats.clusters_seen += 1
            if (cluster.frequency or 0) < self._min_frequency:
                stats.skipped_low_frequency += 1
                continue
            if follower_count is not None and not (
                self._min_followers <= follower_count <= self._max_followers
            ):
                stats.skipped_out_of_band += 1
                continue
            key = normalize_label(cluster.label or "")
            if not key:
                continue
            if matched_exclusion(key, self._discovery.exclusions) is not None:
                stats.skipped_excluded += 1
                continue
            source = _Source(
                cluster_id=cluster.id,
                creator_id=str(cluster.creator_id),
                label=cluster.label,
                frequency=int(cluster.frequency or 0),
                creator_niche=creator_niche,
                follower_count=follower_count,
            )
            per_creator = grouped.setdefault(key, {})
            current = per_creator.get(source.creator_id)
            if current is None or source.frequency > current.frequency:
                per_creator[source.creator_id] = source
            display.setdefault(key, cluster.label.strip())

        for key, per_creator in grouped.items():
            if await registry_fresh(self._session, key):
                stats.skipped_registry_fresh += 1
                continue
            await self._upsert(key, display[key], list(per_creator.values()), stats)

        if stats.created or stats.updated:
            logger.info(
                "Micro-niche suggestions: %d new, %d refreshed (from %d cluster(s))",
                stats.created,
                stats.updated,
                stats.clusters_seen,
            )
        return stats

    async def _upsert(
        self, key: str, label: str, new_sources: list[_Source], stats: SuggestionStats
    ) -> None:
        existing = (
            await self._session.execute(
                select(MicroNicheSuggestion).where(MicroNicheSuggestion.normalized_label == key)
            )
        ).scalar_one_or_none()

        if existing is not None and existing.status != MicroNicheStatus.PENDING:
            stats.skipped_already_decided += 1
            return

        # Merge with what the row already knows, one source per creator:
        # a re-researched creator's fresh cluster replaces their old one.
        by_creator: dict[str, dict[str, Any]] = {}
        if existing is not None:
            for src in existing.sources or []:
                if src.get("creator_id"):
                    by_creator[str(src["creator_id"])] = dict(src)
        for fresh in new_sources:
            by_creator[fresh.creator_id] = fresh.as_json()
        sources = sorted(by_creator.values(), key=lambda s: -int(s.get("frequency", 0)))

        strongest = max(new_sources, key=lambda s: s.frequency)
        top_json = sources[0]
        total = sum(int(s.get("frequency", 0)) for s in sources)

        if existing is None:
            row = MicroNicheSuggestion(
                label=label,
                normalized_label=key,
                status=MicroNicheStatus.PENDING,
                sources=sources,
                total_frequency=total,
                source_creator_count=len(sources),
            )
            self._apply_strongest(row, top_json, strongest)
            try:
                # Two research jobs finishing together can race to create
                # the same label; the unique index decides, and the loser
                # simply refreshes it on its next run.
                async with self._session.begin_nested():
                    self._session.add(row)
                    await self._session.flush()
            except IntegrityError:
                logger.info("Micro-niche %r was created concurrently; skipping", key)
                return
            stats.created += 1
            return

        existing.sources = sources
        existing.total_frequency = total
        existing.source_creator_count = len(sources)
        self._apply_strongest(existing, top_json, strongest)
        await self._session.flush()
        stats.updated += 1

    @staticmethod
    def _apply_strongest(
        row: MicroNicheSuggestion, top_json: dict[str, Any], strongest: _Source
    ) -> None:
        """Point the row at its strongest source. Creator context (niche,
        size) is only known for sources seen in this run, so it is taken
        from this run's strongest when that is also the overall strongest."""
        # Not str(x) or None: str(None) is the truthy string "None".
        cluster_id = top_json.get("cluster_id")
        creator_id = top_json.get("creator_id")
        row.problem_cluster_id = str(cluster_id) if cluster_id else None
        row.creator_id = str(creator_id) if creator_id else None
        if top_json.get("creator_id") == strongest.creator_id:
            row.creator_niche = strongest.creator_niche
            row.follower_count = strongest.follower_count
