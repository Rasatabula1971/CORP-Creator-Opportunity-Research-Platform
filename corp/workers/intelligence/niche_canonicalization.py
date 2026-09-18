"""Niche canonicalization & deduplication (Slice 9, §12).

Staged NicheCandidate rows are promoted to canonical Niche rows or merged
into existing niches when a near-duplicate is detected.

Deduplication strategy (no LLM required):

1. **Exact name match** (case-insensitive): candidate label matches an
   existing Niche.canonical_name or NicheAlias.alias → merge.
2. **Embedding similarity**: embed the candidate label, compare against all
   existing niche labels; cosine ≥ threshold → merge.
3. **No match**: promote to a new Niche row.

A merged candidate becomes a NicheAlias on the matched niche.
A promoted candidate creates a new Niche and links back via niche_id.
Both create a CampaignNiche row connecting the niche to the campaign.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign_niche import CampaignNiche
from corp.core.models.niche import Niche, NicheAlias, NicheLifecycleStatus
from corp.core.models.niche_candidate import (
    NicheCandidate,
    NicheCandidateStatus,
)
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.workers.intelligence.embeddings import Embedder, embed_texts_async
from corp.workers.intelligence.runs import (
    PipelineStats,
    fail_run,
    finish_run,
    start_run,
)

logger = logging.getLogger(__name__)

PIPELINE = "niche_canonicalization"
DEFAULT_SIMILARITY_THRESHOLD = 0.82


@dataclass(frozen=True, slots=True)
class CanonConfig:
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD


class NicheCanonicalizer:
    def __init__(
        self,
        embedder: Embedder,
        session: AsyncSession,
        config: CanonConfig | None = None,
    ) -> None:
        self._embedder = embedder
        self._session = session
        self._cfg = config or CanonConfig()

    async def canonicalize(self, campaign_id: str) -> ResearchRun:
        """Promote or merge every staged candidate for a campaign."""
        embedder_name = getattr(self._embedder, "model_name", "unknown")
        run = await start_run(
            self._session,
            pipeline=PIPELINE,
            creator_id=None,
            config={
                "similarity_threshold": self._cfg.similarity_threshold,
                "embedder": embedder_name,
            },
            prompt_versions={},
            model_versions={"embedder": embedder_name},
            scope=RunScope.NICHE,
            run_type=RunType.NICHE_DISCOVERY,
            campaign_id=campaign_id,
        )
        stats = PipelineStats()

        try:
            candidates = await self._staged_candidates(campaign_id)
            stats.extra["candidates"] = len(candidates)

            if not candidates:
                stats.extra.update(promoted=0, merged=0, campaign_niches_created=0)
                return await finish_run(self._session, run, stats)

            existing_niches = await self._all_niches()
            niche_labels = [n.canonical_name for n in existing_niches]
            niche_embeddings = (
                await embed_texts_async(niche_labels, self._embedder) if niche_labels else None
            )

            promoted = 0
            merged = 0
            campaign_niches_created = 0

            for cand in candidates:
                match = await self._find_match(
                    cand.label, existing_niches, niche_embeddings
                )

                if match is not None:
                    niche = match
                    cand.status = NicheCandidateStatus.MERGED
                    cand.niche_id = niche.id
                    await self._add_alias_if_new(niche.id, cand.label)
                    merged += 1
                    logger.info(
                        "Merged candidate %r into niche %r (%s)",
                        cand.label, niche.canonical_name, niche.id,
                    )
                else:
                    niche = Niche(
                        canonical_name=cand.label,
                        description=cand.description,
                        lifecycle_status=NicheLifecycleStatus.CANDIDATE,
                        first_discovered_at=cand.earliest_collected_at
                        or datetime.now(UTC),
                    )
                    self._session.add(niche)
                    await self._session.flush()
                    cand.status = NicheCandidateStatus.PROMOTED
                    cand.niche_id = niche.id
                    existing_niches.append(niche)
                    if niche_embeddings is not None:
                        new_emb = await embed_texts_async([cand.label], self._embedder)
                        niche_embeddings = np.vstack([niche_embeddings, new_emb])
                    else:
                        niche_embeddings = await embed_texts_async([cand.label], self._embedder)
                    niche_labels.append(niche.canonical_name)
                    promoted += 1
                    logger.info(
                        "Promoted candidate %r → niche %s", cand.label, niche.id,
                    )

                cn_created = await self._ensure_campaign_niche(
                    campaign_id, niche.id, cand
                )
                campaign_niches_created += cn_created
                await self._session.flush()
                stats.ok()

            stats.extra.update(
                promoted=promoted,
                merged=merged,
                campaign_niches_created=campaign_niches_created,
            )
            return await finish_run(self._session, run, stats)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception("Canonicalization failed for campaign %s", campaign_id)
            raise

    async def _find_match(
        self,
        label: str,
        existing: list[Niche],
        embeddings: np.ndarray | None,
    ) -> Niche | None:
        label_lower = label.lower().strip()
        for niche in existing:
            if niche.canonical_name.lower().strip() == label_lower:
                return niche

        alias_match = await self._find_alias_match(label)
        if alias_match is not None:
            return alias_match

        if embeddings is None or len(existing) == 0:
            return None

        cand_emb = await embed_texts_async([label], self._embedder)
        sims = _cosine_batch(cand_emb[0], embeddings)
        best_idx = int(np.argmax(sims))
        if sims[best_idx] >= self._cfg.similarity_threshold:
            return existing[best_idx]
        return None

    async def _staged_candidates(self, campaign_id: str) -> list[NicheCandidate]:
        result = await self._session.execute(
            select(NicheCandidate)
            .where(
                NicheCandidate.campaign_id == campaign_id,
                NicheCandidate.status == NicheCandidateStatus.STAGED,
                NicheCandidate.superseded_at.is_(None),
            )
            .order_by(NicheCandidate.evidence_count.desc())
        )
        return list(result.scalars().all())

    async def _all_niches(self) -> list[Niche]:
        result = await self._session.execute(
            select(Niche).order_by(Niche.canonical_name)
        )
        return list(result.scalars().all())

    async def _find_alias_match(self, label: str) -> Niche | None:
        """Check if the label matches any existing NicheAlias (case-insensitive)."""
        result = await self._session.execute(
            select(NicheAlias).where(
                func.lower(NicheAlias.alias) == label.lower().strip()
            )
        )
        alias = result.scalars().first()
        if alias is None:
            return None
        return await self._session.get(Niche, alias.niche_id)

    async def _add_alias_if_new(self, niche_id: str, alias_text: str) -> bool:
        existing = await self._session.execute(
            select(NicheAlias).where(
                func.lower(NicheAlias.alias) == alias_text.lower().strip()
            )
        )
        if existing.scalar_one_or_none() is not None:
            return False
        also_canonical = await self._session.execute(
            select(Niche).where(
                func.lower(Niche.canonical_name) == alias_text.lower().strip()
            )
        )
        if also_canonical.scalar_one_or_none() is not None:
            return False
        self._session.add(NicheAlias(niche_id=niche_id, alias=alias_text))
        await self._session.flush()
        return True

    async def _ensure_campaign_niche(
        self, campaign_id: str, niche_id: str, cand: NicheCandidate
    ) -> int:
        existing = await self._session.execute(
            select(CampaignNiche).where(
                CampaignNiche.campaign_id == campaign_id,
                CampaignNiche.niche_id == niche_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return 0
        self._session.add(
            CampaignNiche(
                campaign_id=campaign_id,
                niche_id=niche_id,
                creator_count_observed=cand.author_count,
            )
        )
        await self._session.flush()
        return 1


def _cosine_batch(vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1)
    vec_norm = np.linalg.norm(vec)
    denom = norms * vec_norm
    denom = np.where(denom == 0, 1.0, denom)
    return np.clip(matrix @ vec / denom, 0.0, 1.0)  # type: ignore[no-any-return]
