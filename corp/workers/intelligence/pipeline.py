"""Intelligence pipeline — orchestrates extraction and topic classification."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.content import AudienceInteraction, ContentItem
from corp.core.models.creator import CreatorStatus
from corp.core.models.evidence import Evidence
from corp.core.models.intelligence import ProblemObservation
from corp.core.models.workflow import ResearchRun
from corp.workers.intelligence.creator_content import (
    CREATOR_PROMPT_VERSION,
    extract_creator_problems,
)
from corp.workers.intelligence.errors import LLMCallError
from corp.workers.intelligence.extraction import (
    EXTRACTION_PROMPT_VERSION,
    extract_observations,
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


class IntelligencePipeline:
    """Runs extraction + topic classification for a creator's collected data.

    Idempotent: an interaction that already has observations from the same
    prompt version and model is skipped, so re-runs only extract new comments.
    """

    def __init__(
        self,
        provider: LLMProvider,
        session: AsyncSession,
        max_failure_rate: float = DEFAULT_MAX_FAILURE_RATE,
    ) -> None:
        self._provider = provider
        self._session = session
        self._max_failure_rate = max_failure_rate

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

        try:
            async with stage(
                self._session,
                creator_id,
                working=CreatorStatus.EXTRACTING,
                done=CreatorStatus.EXTRACTED,
            ):
                await self._extract_problems(creator_id, stats)
                await self._extract_creator_side(creator_id, stats)
                await self._classify_and_store_topics(creator_id, stats)
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
        result = await self._session.execute(
            select(AudienceInteraction, ContentItem.title, ContentItem.platform)
            .join(ContentItem, AudienceInteraction.content_item_id == ContentItem.id)
            .where(ContentItem.creator_id == creator_id)
        )

        for interaction, content_title, platform in result.all():
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

            try:
                observations = await extract_observations(
                    provider=self._provider,
                    comment_text=interaction.text,
                    author=interaction.author_handle,
                    content_title=content_title,
                    platform=platform or "unknown",
                )
            except LLMCallError as exc:
                stats.fail(exc)
                continue

            for obs in observations:
                self._session.add(
                    ProblemObservation(
                        evidence_id=evidence.id,
                        text=obs.text,
                        category=obs.category,
                        is_inferred=obs.is_inferred,
                        extraction_prompt_version=EXTRACTION_PROMPT_VERSION,
                        model_version=self._provider.model_name,
                        confidence=obs.confidence,
                        source_side="audience",
                    )
                )
            stats.ok()
            await self._session.flush()

    async def _find_evidence(self, external_id: str) -> Evidence | None:
        """Newest evidence row for a source id (re-collection appends, never updates)."""
        result = await self._session.execute(
            select(Evidence)
            .where(Evidence.source_id == external_id)
            .order_by(Evidence.collected_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

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
                ProblemObservation.model_version == self._provider.model_name,
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

            for obs in observations:
                self._session.add(
                    ProblemObservation(
                        evidence_id=evidence.id,
                        text=obs.text,
                        category=obs.category,
                        is_inferred=obs.is_inferred,
                        extraction_prompt_version=CREATOR_PROMPT_VERSION,
                        model_version=self._provider.model_name,
                        confidence=obs.confidence,
                        source_side="creator",
                    )
                )
            stats.ok()
            await self._session.flush()

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
