"""Evidence → candidate niche (Slice 8, §15 Stage A, §16).

    discovery evidence for a campaign
    → embed (same local sentence-transformer as clustering)
    → UMAP + HDBSCAN (same code path as problem clustering)
    → one staged NicheCandidate per cluster, with a member row per evidence
    → LLM names the cluster from its texts; an ungrounded or failed answer
      leaves the deterministic keyword label in place

Nothing here can create a candidate without evidence: a candidate is only ever
built from a cluster, and a cluster is a set of evidence rows. Noise points
(HDBSCAN label -1) produce nothing. A rerun for the same campaign supersedes
that campaign's still-staged candidates from earlier runs (latest wins; rows
are never deleted).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.evidence import Evidence
from corp.core.models.niche_candidate import (
    NicheCandidate,
    NicheCandidateEvidence,
    NicheCandidateStatus,
)
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.core.state.research_run import validate_run_type
from corp.workers.intelligence.clustering import ClusteringConfig, cluster_observations
from corp.workers.intelligence.embeddings import Embedder, embed_texts_async
from corp.workers.intelligence.errors import LLMCallError
from corp.workers.intelligence.niche_naming import NAMING_PROMPT_VERSION, name_cluster
from corp.workers.intelligence.runs import (
    PipelineStats,
    fail_run,
    finish_run,
    start_run,
    supersede,
)
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)

PIPELINE = "niche_candidates"


@dataclass(frozen=True, slots=True)
class CandidateConfig:
    # Discovery evidence sets are small (tens of items in Stage A); the
    # problem-clustering defaults (3 / 2) are kept, but exposed.
    min_cluster_size: int = 3
    min_samples: int = 2


class NicheCandidateGenerator:
    def __init__(
        self,
        embedder: Embedder,
        provider: LLMProvider | None,
        session: AsyncSession,
        config: CandidateConfig | None = None,
    ) -> None:
        self._embedder = embedder
        self._provider = provider
        self._session = session
        self._config = config or CandidateConfig()

    async def generate(self, campaign_id: str) -> ResearchRun:
        """Group the campaign's discovery evidence into staged candidates. Returns the run."""
        if await self._session.get(Campaign, campaign_id) is None:
            raise ValueError(f"Campaign not found: {campaign_id}")
        validate_run_type(RunType.NICHE_DISCOVERY, creator_id=None, niche_id=None)

        embedder_name = getattr(self._embedder, "model_name", "unknown")
        provider_name = self._provider.model_name if self._provider else None
        run = await start_run(
            self._session,
            pipeline=PIPELINE,
            creator_id=None,
            config={
                "min_cluster_size": self._config.min_cluster_size,
                "min_samples": self._config.min_samples,
                "embedder": embedder_name,
                "provider": provider_name,
            },
            prompt_versions={"naming": NAMING_PROMPT_VERSION} if self._provider else {},
            model_versions={"embedder": embedder_name, "primary": provider_name},
            scope=RunScope.NICHE,
            run_type=RunType.NICHE_DISCOVERY,
            campaign_id=campaign_id,
        )
        stats = PipelineStats()

        try:
            evidence = await self._load_evidence(campaign_id)
            stats.extra["evidence"] = len(evidence)
            superseded = await supersede(
                self._session,
                NicheCandidate,
                NicheCandidate.campaign_id == campaign_id,
                NicheCandidate.status == NicheCandidateStatus.STAGED,
            )
            stats.extra["superseded"] = superseded

            clusters: list[Any] = []
            embeddings = np.empty((0, 0), dtype=np.float32)
            if evidence:
                texts = [e.raw_text for e in evidence]
                embeddings = await embed_texts_async(texts, self._embedder)
                clusters = cluster_observations(
                    texts,
                    embeddings,
                    [e.collected_at for e in evidence],
                    ClusteringConfig(
                        min_cluster_size=self._config.min_cluster_size,
                        min_samples=self._config.min_samples,
                    ),
                )
            stats.extra["clusters"] = len(clusters)
            clustered = 0
            llm_failures = 0
            ungrounded = 0
            for cr in clusters:
                members = [evidence[i] for i in cr.member_indices]
                clustered += len(members)
                candidate = self._candidate(run, campaign_id, cr, members, embedder_name)
                if self._provider is not None:
                    try:
                        named = await name_cluster(
                            self._provider,
                            [m.raw_text for m in members],
                            platform=self._platform_label(members),
                        )
                    except LLMCallError as exc:
                        llm_failures += 1
                        candidate.extra = {"naming_error": str(exc)[:500]}
                    else:
                        candidate.naming_prompt_version = NAMING_PROMPT_VERSION
                        candidate.naming_model_version = self._provider.model_name
                        candidate.is_broad_domain = named.is_broad_domain
                        candidate.naming_confidence = named.confidence
                        if named.grounded:
                            candidate.label = named.name
                            candidate.description = named.description or candidate.description
                            candidate.naming_method = "llm"
                            candidate.naming_terms = named.evidence_terms
                        else:
                            ungrounded += 1
                            candidate.extra = {
                                "rejected_llm_name": named.name,
                                "ungrounded_terms": named.ungrounded_terms,
                            }
                self._session.add(candidate)
                await self._session.flush()
                centroid = embeddings[list(cr.member_indices)].mean(axis=0)
                for idx, ev in zip(cr.member_indices, members, strict=True):
                    self._session.add(
                        NicheCandidateEvidence(
                            candidate_id=candidate.id,
                            evidence_id=ev.id,
                            similarity=_cosine(embeddings[idx], centroid),
                        )
                    )
                await self._session.flush()
                stats.ok()

            stats.extra.update(
                {
                    "candidates": len(clusters),
                    "noise": len(evidence) - clustered,
                    "llm_naming_failures": llm_failures,
                    "llm_names_ungrounded": ungrounded,
                }
            )
            if self._provider is not None:
                used = getattr(self._provider, "models_used", None)
                run.model_versions = {
                    **(run.model_versions or {}),
                    "used": sorted(used()) if used else [self._provider.model_name],
                }
            return await finish_run(self._session, run, stats)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception("Niche candidate generation failed for campaign %s", campaign_id)
            raise

    async def _load_evidence(self, campaign_id: str) -> list[Evidence]:
        """Every non-empty evidence row collected by this campaign's discovery runs."""
        result = await self._session.execute(
            select(Evidence)
            .join(ResearchRun, ResearchRun.id == Evidence.research_run_id)
            .where(
                ResearchRun.campaign_id == campaign_id,
                ResearchRun.run_type == RunType.NICHE_DISCOVERY.value,
                Evidence.raw_text != "",
            )
            .order_by(Evidence.collected_at, Evidence.id)
        )
        return list(result.scalars().all())

    @staticmethod
    def _candidate(
        run: ResearchRun,
        campaign_id: str,
        cr: Any,
        members: list[Evidence],
        embedder_name: str,
    ) -> NicheCandidate:
        collected = [m.collected_at for m in members if m.collected_at is not None]
        return NicheCandidate(
            campaign_id=campaign_id,
            research_run_id=run.id,
            label=cr.label,
            description=cr.description,
            naming_method="keywords",
            evidence_count=len(members),
            source_count=len({m.source_platform for m in members}),
            author_count=len({m.author_handle for m in members if m.author_handle}),
            earliest_collected_at=min(collected) if collected else None,
            latest_collected_at=max(collected) if collected else None,
            representative_text=cr.description,
            embedding_model=embedder_name,
        )

    @staticmethod
    def _platform_label(members: list[Evidence]) -> str:
        platforms = sorted({m.source_platform for m in members})
        return platforms[0] if len(platforms) == 1 else "mixed"


def _cosine(vector: np.ndarray, centroid: np.ndarray) -> float:
    denom = float(np.linalg.norm(vector) * np.linalg.norm(centroid))
    if denom == 0.0:
        return 0.0
    return round(float(np.clip(vector @ centroid / denom, 0.0, 1.0)), 4)
