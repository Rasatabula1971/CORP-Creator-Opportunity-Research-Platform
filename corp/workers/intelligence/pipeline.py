"""Intelligence pipeline — orchestrates extraction and topic classification."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.content import AudienceInteraction, ContentItem
from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.evidence import Evidence
from corp.core.models.intelligence import ProblemObservation
from corp.core.models.workflow import ResearchRun
from corp.workers.intelligence.extraction import (
    EXTRACTION_PROMPT_VERSION,
    extract_observations,
    extract_observations_batch,
)
from corp.workers.intelligence.topics import TOPIC_PROMPT_VERSION, classify_topics
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)

BATCH_SIZE = 15


class IntelligencePipeline:
    """Runs extraction + topic classification for a creator's collected data."""

    def __init__(self, provider: LLMProvider, session: AsyncSession) -> None:
        self._provider = provider
        self._session = session

    async def run(self, creator_id: str) -> ResearchRun:
        """Run intelligence pipeline for a creator.

        Loads all interactions + evidence, extracts ProblemObservations
        in batches with cross-comment synthesis, classifies topics,
        and pins prompt/model versions on the ResearchRun.
        """
        run = ResearchRun(
            creator_id=creator_id,
            status="running",
            started_at=datetime.now(timezone.utc),
            config_snapshot={"pipeline": "intelligence", "provider": self._provider.model_name},
            prompt_versions={
                "extraction": EXTRACTION_PROMPT_VERSION,
                "topics": TOPIC_PROMPT_VERSION,
            },
            model_versions={"primary": self._provider.model_name},
        )
        self._session.add(run)
        await self._session.flush()

        await self._transition_status(creator_id, CreatorStatus.EXTRACTING)

        try:
            await self._extract_problems(creator_id, run.id)
            topics = await self._classify_creator_topics(creator_id)
            await self._store_topics(creator_id, topics)
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            await self._transition_status(creator_id, CreatorStatus.EXTRACTED)
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
            select(AudienceInteraction, ContentItem.title, ContentItem.platform, ContentItem.id)
            .join(ContentItem, AudienceInteraction.content_item_id == ContentItem.id)
            .where(ContentItem.creator_id == creator_id)
        )
        rows = result.all()

        if not rows:
            return

        evidence_map = await self._load_evidence_map(
            [interaction.external_id for interaction, *_ in rows]
        )

        groups: dict[str, list[tuple]] = {}
        for interaction, content_title, platform, content_item_id in rows:
            key = content_item_id
            groups.setdefault(key, []).append((interaction, content_title, platform))

        for content_item_id, group_rows in groups.items():
            _, content_title, platform = group_rows[0]
            await self._extract_batch(
                group_rows, content_title, platform, evidence_map, research_run_id
            )

    async def _extract_batch(
        self,
        rows: list[tuple],
        content_title: str | None,
        platform: str,
        evidence_map: dict[str, Evidence],
        research_run_id: str,
    ) -> None:
        """Extract observations from a group of comments in batches."""
        valid_rows = [
            (interaction, evidence_map[interaction.external_id])
            for interaction, _, _ in rows
            if interaction.external_id in evidence_map
        ]

        if not valid_rows:
            return

        for batch_start in range(0, len(valid_rows), BATCH_SIZE):
            batch = valid_rows[batch_start : batch_start + BATCH_SIZE]

            if len(batch) >= 3:
                comments = [
                    {"text": interaction.text, "author": interaction.author_handle}
                    for interaction, _ in batch
                ]
                observations = await extract_observations_batch(
                    provider=self._provider,
                    comments=comments,
                    content_title=content_title,
                    platform=platform,
                )
                for obs in observations:
                    evidence = self._pick_evidence_for_observation(obs, batch)
                    po = ProblemObservation(
                        evidence_id=evidence.id,
                        text=obs.text,
                        category=obs.category,
                        is_inferred=obs.is_inferred,
                        sentiment=obs.sentiment,
                        urgency=obs.urgency,
                        extraction_prompt_version=EXTRACTION_PROMPT_VERSION,
                        model_version=self._provider.model_name,
                        confidence=obs.confidence,
                    )
                    self._session.add(po)
            else:
                for interaction, evidence in batch:
                    observations = await extract_observations(
                        provider=self._provider,
                        comment_text=interaction.text,
                        author=interaction.author_handle,
                        content_title=content_title,
                        platform=platform,
                    )
                    for obs in observations:
                        po = ProblemObservation(
                            evidence_id=evidence.id,
                            text=obs.text,
                            category=obs.category,
                            is_inferred=obs.is_inferred,
                            sentiment=obs.sentiment,
                            urgency=obs.urgency,
                            extraction_prompt_version=EXTRACTION_PROMPT_VERSION,
                            model_version=self._provider.model_name,
                            confidence=obs.confidence,
                        )
                        self._session.add(po)

            await self._session.flush()

    def _pick_evidence_for_observation(
        self,
        obs,
        batch: list[tuple],
    ) -> "Evidence":
        """Pick the best evidence row for a batch-extracted observation."""
        if obs.source_indices:
            for idx in obs.source_indices:
                if 0 <= idx < len(batch):
                    return batch[idx][1]
        return batch[0][1]

    async def _load_evidence_map(self, external_ids: list[str]) -> dict[str, "Evidence"]:
        """Load the most recent Evidence row for each external_id."""
        if not external_ids:
            return {}
        result = await self._session.execute(
            select(Evidence)
            .where(Evidence.source_id.in_(external_ids))
            .order_by(Evidence.collected_at.desc())
        )
        evidence_list = result.scalars().all()
        evidence_map: dict[str, Evidence] = {}
        for ev in evidence_list:
            if ev.source_id not in evidence_map:
                evidence_map[ev.source_id] = ev
        return evidence_map

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

    async def _transition_status(self, creator_id: str, status: CreatorStatus) -> None:
        result = await self._session.execute(
            select(Creator).where(Creator.id == creator_id)
        )
        creator = result.scalars().first()
        if creator:
            creator.status = status
            await self._session.flush()

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
