"""Intelligence pipeline — orchestrates extraction and topic classification."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.content import AudienceInteraction, ContentItem
from corp.core.models.creator import CreatorStatus
from corp.core.models.evidence import Evidence
from corp.core.models.intelligence import ProblemObservation
from corp.core.models.workflow import ResearchRun
from corp.warmstore.sync import mirror_observations
from corp.workers.intelligence.creator_content import (
    CREATOR_PROMPT_VERSION,
    extract_creator_problems,
)
from corp.workers.intelligence.errors import LLMCallError
from corp.workers.intelligence.extraction import (
    EXTRACTION_PROMPT_VERSION,
    extract_observations,
    extract_observations_batch,
)
from corp.workers.intelligence.runs import (
    DEFAULT_MAX_FAILURE_RATE,
    PipelineStats,
    fail_run,
    finish_run,
    stage,
    start_run,
)
from corp.workers.intelligence.topics import TOPIC_PROMPT_VERSION, classify_topics
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)

# Batch size for cross-comment extraction. 15 balances "enough context for the
# LLM to spot recurring patterns" against "small enough to stay well under
# per-request token limits with room for 500-char comments each." Falls back
# to per-comment extraction for anything smaller than a full batch tail.
DEFAULT_BATCH_SIZE = 15


class IntelligencePipeline:
    """Runs extraction + topic classification for a creator's collected data.

    Idempotent: an interaction that already has observations from the same
    prompt version and model is skipped, so re-runs only extract new comments.

    Uses batch extraction (up to ``batch_size`` comments per content item at
    a time) so the LLM can spot patterns that only emerge across multiple
    comments (main-lineage tier-2 capability). Every observation persists its
    ``sentiment`` and ``urgency``; inferred cross-comment observations anchor
    to the first supporting evidence row so the evidence chain never breaks.
    """

    def __init__(
        self,
        provider: LLMProvider,
        session: AsyncSession,
        max_failure_rate: float = DEFAULT_MAX_FAILURE_RATE,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._provider = provider
        self._session = session
        self._max_failure_rate = max_failure_rate
        self._batch_size = max(1, batch_size)

    async def run(self, creator_id: str) -> ResearchRun:
        run = await start_run(
            self._session,
            pipeline="intelligence",
            creator_id=creator_id,
            config={"provider": self._provider.model_name},
            prompt_versions={
                "extraction": EXTRACTION_PROMPT_VERSION,
                "creator_extraction": CREATOR_PROMPT_VERSION,
                "topics": TOPIC_PROMPT_VERSION,
            },
            model_versions={"primary": self._provider.model_name},
        )
        stats = PipelineStats()

        await self._transition_status(creator_id, CreatorStatus.EXTRACTING)

        try:
            async with stage(
                self._session,
                creator_id,
                working=CreatorStatus.EXTRACTING,
                done=CreatorStatus.EXTRACTED,
                run=run,
            ):
                await self._extract_problems(creator_id, stats)
                await self._extract_creator_side(creator_id, stats)
                await self._classify_and_store_topics(creator_id, stats)
                # "primary" is what the run started with; "used" is what actually
                # answered, which a pool can change mid-run (PDR #9 provenance).
                run.model_versions = {**(run.model_versions or {}), "used": self._models_used()}
                await finish_run(
                    self._session, run, stats, max_failure_rate=self._max_failure_rate
                )
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception("Intelligence pipeline failed for creator %s", creator_id)
            raise

        return run

    # ── Extraction ───────────────────────────────────────────────────

    async def _extract_problems(self, creator_id: str, stats: PipelineStats) -> None:
        """Extract per-comment + cross-comment observations, one content item at a time.

        Interactions are grouped by content item because cross-comment
        synthesis only makes sense within one piece of content (a comment on
        video A shouldn't be batched with one on video B). Within each content
        item's comments, we batch up to ``self._batch_size`` at a time.
        """
        result = await self._session.execute(
            select(AudienceInteraction, ContentItem.id, ContentItem.title, ContentItem.platform)
            .join(ContentItem, AudienceInteraction.content_item_id == ContentItem.id)
            .where(ContentItem.creator_id == creator_id)
            .order_by(ContentItem.id, AudienceInteraction.id)
        )

        grouped: dict[str, dict] = {}
        for interaction, ci_id, title, platform in result.all():
            entry = grouped.setdefault(
                ci_id,
                {"title": title, "platform": platform, "interactions": []},
            )
            entry["interactions"].append(interaction)

        for ci_id, group in grouped.items():
            interactions: list[AudienceInteraction] = group["interactions"]
            title = group["title"]
            platform = group["platform"] or "unknown"

            # Resolve evidence + skip-if-already-extracted per interaction up front,
            # so a whole batch can share the pre-flight work.
            pending: list[tuple[AudienceInteraction, Evidence]] = []
            for interaction in interactions:
                evidence = await self._find_evidence(interaction.external_id)
                if evidence is None:
                    logger.warning(
                        "No evidence for interaction %s, skipping extraction",
                        interaction.external_id,
                    )
                    stats.skip()
                    continue
                if await self._already_extracted(interaction.external_id):
                    stats.skip()
                    continue
                pending.append((interaction, evidence))

            for chunk_start in range(0, len(pending), self._batch_size):
                chunk = pending[chunk_start : chunk_start + self._batch_size]
                await self._extract_chunk(chunk, title, platform, stats)

    async def _extract_chunk(
        self,
        chunk: list[tuple[AudienceInteraction, Evidence]],
        content_title: str | None,
        platform: str,
        stats: PipelineStats,
    ) -> None:
        """Run one batched extraction and persist its observations."""
        if not chunk:
            return

        if len(chunk) == 1:
            # Single-comment path — no batch synthesis possible with one row.
            interaction, evidence = chunk[0]
            try:
                observations = await extract_observations(
                    provider=self._provider,
                    comment_text=interaction.text,
                    author=interaction.author_handle,
                    content_title=content_title,
                    platform=platform,
                )
            except LLMCallError as exc:
                stats.fail(exc)
                return
            self._persist_observations(observations, anchor_evidence=evidence)
            stats.ok()
            await self._session.flush()
            return

        payload = [
            {"text": interaction.text, "author": interaction.author_handle}
            for interaction, _ in chunk
        ]
        try:
            observations = await extract_observations_batch(
                provider=self._provider,
                comments=payload,
                content_title=content_title,
                platform=platform,
            )
        except LLMCallError as exc:
            stats.fail(exc)
            return

        # Map each observation to a supporting evidence row via source_indices.
        # An inferred observation without indices anchors to the first comment
        # in the chunk so the append-only evidence chain (§9) never breaks.
        new_obs: list[ProblemObservation] = []
        for obs in observations:
            indices = obs.source_indices or [0]
            valid_indices = [i for i in indices if 0 <= i < len(chunk)]
            if not valid_indices:
                valid_indices = [0]
            anchor_index = valid_indices[0]
            anchor_evidence = chunk[anchor_index][1]
            po = ProblemObservation(
                evidence_id=anchor_evidence.id,
                text=obs.text,
                category=obs.category,
                is_inferred=obs.is_inferred,
                extraction_prompt_version=EXTRACTION_PROMPT_VERSION,
                model_version=self._provider.model_name,
                confidence=obs.confidence,
                sentiment=obs.sentiment,
                urgency=obs.urgency,
                source_side="audience",
            )
            self._session.add(po)
            new_obs.append(po)
        stats.ok()
        await self._session.flush()
        await mirror_observations(new_obs)

    def _persist_observations(
        self,
        observations: list,
        anchor_evidence: Evidence,
    ) -> list[ProblemObservation]:
        """Save single-comment observations against a specific evidence row."""
        new_obs: list[ProblemObservation] = []
        for obs in observations:
            po = ProblemObservation(
                evidence_id=anchor_evidence.id,
                text=obs.text,
                category=obs.category,
                is_inferred=obs.is_inferred,
                extraction_prompt_version=EXTRACTION_PROMPT_VERSION,
                model_version=self._provider.model_name,
                confidence=obs.confidence,
                sentiment=obs.sentiment,
                urgency=obs.urgency,
                source_side="audience",
            )
            self._session.add(po)
            new_obs.append(po)
        return new_obs

    async def _find_evidence(self, external_id: str) -> Evidence | None:
        """Newest evidence row for a source id (re-collection appends, never updates)."""
        result = await self._session.execute(
            select(Evidence)
            .where(Evidence.source_id == external_id)
            .order_by(Evidence.collected_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _model_family(self) -> list[str]:
        """Model names that count as "already done" for idempotency.

        A pooled provider may answer with any of its members, and which one
        answers can change between runs (a daily cap today, not tomorrow).
        Those members are one family: work done by any of them is done. A
        genuinely different model (new deployment) still re-extracts.
        """
        members = getattr(self._provider, "member_names", None)
        return list(members()) if members else [self._provider.model_name]

    def _models_used(self) -> list[str]:
        used = getattr(self._provider, "models_used", None)
        return sorted(used()) if used else [self._provider.model_name]

    async def _already_extracted(
        self,
        external_id: str,
        prompt_version: str = EXTRACTION_PROMPT_VERSION,
        source_side: str = "audience",
    ) -> bool:
        result = await self._session.execute(
            select(ProblemObservation.id)
            .join(Evidence, Evidence.id == ProblemObservation.evidence_id)
            .where(
                Evidence.source_id == external_id,
                ProblemObservation.extraction_prompt_version == prompt_version,
                ProblemObservation.model_version.in_(self._model_family()),
                ProblemObservation.source_side == source_side,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    # ── Creator-side extraction ──────────────────────────────────────

    async def _extract_creator_side(self, creator_id: str, stats: PipelineStats) -> None:
        """What the creator's own titles, descriptions and transcripts address."""
        result = await self._session.execute(
            select(ContentItem).where(ContentItem.creator_id == creator_id)
        )
        for ci in result.scalars().all():
            evidence = await self._find_evidence(ci.external_id)
            if evidence is None:
                stats.skip()
                continue
            if await self._already_extracted(
                ci.external_id, CREATOR_PROMPT_VERSION, source_side="creator"
            ):
                stats.skip()
                continue

            caption = await self._find_evidence(f"caption_{ci.external_id}")
            body = "\n\n".join(
                part for part in (ci.description, caption.raw_text if caption else None) if part
            )
            if not body and not ci.title:
                stats.skip()
                continue

            try:
                observations = await extract_creator_problems(
                    self._provider, ci.title, body, platform=ci.platform or "unknown"
                )
            except LLMCallError as exc:
                stats.fail(exc)
                continue

            new_obs = []
            for obs in observations:
                po = ProblemObservation(
                    evidence_id=evidence.id,
                    text=obs.text,
                    category=obs.category,
                    is_inferred=obs.is_inferred,
                    extraction_prompt_version=CREATOR_PROMPT_VERSION,
                    model_version=self._provider.model_name,
                    confidence=obs.confidence,
                    sentiment=getattr(obs, "sentiment", "neutral"),
                    urgency=getattr(obs, "urgency", "low"),
                    source_side="creator",
                )
                self._session.add(po)
                new_obs.append(po)
            stats.ok()
            await self._session.flush()
            await mirror_observations(new_obs)

    # ── Topics ───────────────────────────────────────────────────────

    async def _classify_and_store_topics(self, creator_id: str, stats: PipelineStats) -> None:
        result = await self._session.execute(
            select(ContentItem).where(ContentItem.creator_id == creator_id)
        )
        content_items = list(result.scalars().all())
        if not content_items:
            return

        items_data = [
            {"title": ci.title or "", "description": ci.description or ""}
            for ci in content_items
        ]
        platform = content_items[0].platform or "unknown"
        try:
            topics = await classify_topics(self._provider, items_data, platform=platform)
        except LLMCallError as exc:
            stats.fail(exc)
            return

        stats.ok()
        stats.extra["topics"] = len(topics)
        if not topics:
            return
        for ci in content_items:
            ci.topics = topics
        await self._session.flush()
