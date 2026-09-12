"""Intelligence pipeline — orchestrates extraction and topic classification."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.content import AudienceInteraction, ContentItem
from corp.core.models.evidence import Evidence
from corp.core.models.intelligence import ProblemObservation
from corp.core.models.workflow import ResearchRun
from corp.workers.intelligence.extraction import (
    EXTRACTION_PROMPT_VERSION,
    extract_observations,
)
from corp.workers.intelligence.topics import TOPIC_PROMPT_VERSION, classify_topics
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)


class IntelligencePipeline:
    """Runs extraction + topic classification for a creator's collected data."""

    def __init__(self, provider: LLMProvider, session: AsyncSession) -> None:
        self._provider = provider
        self._session = session

    async def run(self, creator_id: str) -> ResearchRun:
        """Run intelligence pipeline for a creator.

        Loads all interactions + evidence, extracts ProblemObservations,
        classifies topics, and pins prompt/model versions on the ResearchRun.
        """
        run = ResearchRun(
            creator_id=creator_id,
            status="running",
            config_snapshot={"pipeline": "intelligence", "provider": self._provider.model_name},
            prompt_versions={
                "extraction": EXTRACTION_PROMPT_VERSION,
                "topics": TOPIC_PROMPT_VERSION,
            },
            model_versions={"primary": self._provider.model_name},
        )
        self._session.add(run)
        await self._session.flush()

        try:
            await self._extract_problems(creator_id, run.id)
            topics = await self._classify_creator_topics(creator_id)
            await self._store_topics(creator_id, topics)
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = datetime.now(timezone.utc)
            logger.exception("Intelligence pipeline failed for creator %s", creator_id)
            raise
        finally:
            await self._session.flush()

        return run

    async def _extract_problems(self, creator_id: str, research_run_id: str) -> None:
        result = await self._session.execute(
            select(AudienceInteraction, ContentItem.title)
            .join(ContentItem, AudienceInteraction.content_item_id == ContentItem.id)
            .where(ContentItem.creator_id == creator_id)
        )
        rows = result.all()

        for interaction, content_title in rows:
            evidence = await self._find_evidence(interaction.external_id)
            if evidence is None:
                logger.warning(
                    "No evidence for interaction %s, skipping extraction",
                    interaction.external_id,
                )
                continue

            observations = await extract_observations(
                provider=self._provider,
                comment_text=interaction.text,
                author=interaction.author_handle,
                content_title=content_title,
                platform="youtube",
            )

            for obs in observations:
                po = ProblemObservation(
                    evidence_id=evidence.id,
                    text=obs.text,
                    category=obs.category,
                    is_inferred=obs.is_inferred,
                    extraction_prompt_version=EXTRACTION_PROMPT_VERSION,
                    model_version=self._provider.model_name,
                    confidence=obs.confidence,
                )
                self._session.add(po)

            await self._session.flush()

    async def _find_evidence(self, external_id: str) -> Evidence | None:
        result = await self._session.execute(
            select(Evidence)
            .where(Evidence.source_id == external_id)
            .order_by(Evidence.collected_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def _classify_creator_topics(self, creator_id: str) -> list[dict]:
        result = await self._session.execute(
            select(ContentItem).where(ContentItem.creator_id == creator_id)
        )
        content_items = result.scalars().all()

        if not content_items:
            return []

        items_data = [
            {"title": ci.title or "", "description": ci.description or ""}
            for ci in content_items
        ]
        return await classify_topics(self._provider, items_data)

    async def _store_topics(self, creator_id: str, topics: list[dict]) -> None:
        if not topics:
            return
        result = await self._session.execute(
            select(ContentItem).where(ContentItem.creator_id == creator_id)
        )
        content_items = result.scalars().all()
        for ci in content_items:
            ci.topics = topics
        await self._session.flush()
