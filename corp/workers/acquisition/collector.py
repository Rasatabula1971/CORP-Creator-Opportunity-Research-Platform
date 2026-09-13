"""Acquisition orchestrator — adapter output → DB rows with evidence chain."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.content import AudienceInteraction, ContentItem, ContentType, InteractionType
from corp.core.models.creator import Creator, CreatorPlatformAccount, CreatorStatus
from corp.core.models.evidence import Evidence
from corp.core.models.workflow import ResearchRun
from corp.workers.adapters.base import NormalizedContent, SourceAdapter

logger = logging.getLogger(__name__)

_CONTENT_TYPE_MAP = {
    "video": ContentType.VIDEO,
    "post": ContentType.POST,
    "short": ContentType.SHORT,
    "reel": ContentType.REEL,
    "article": ContentType.ARTICLE,
    "story": ContentType.STORY,
    "thread": ContentType.THREAD,
}

_INTERACTION_TYPE_MAP = {
    "comment": InteractionType.COMMENT,
    "reply": InteractionType.REPLY,
    "question": InteractionType.QUESTION,
    "review": InteractionType.REVIEW,
}


class AcquisitionCollector:
    """Persists adapter output into ContentItem, AudienceInteraction, and Evidence rows."""

    def __init__(self, adapter: SourceAdapter, session: AsyncSession) -> None:
        self._adapter = adapter
        self._session = session

    async def collect_creator_data(
        self,
        identifier: str,
        creator_id: str,
    ) -> ResearchRun:
        """Collect all data for a creator and persist to DB.

        Args:
            identifier: Platform-specific identifier (e.g. YouTube channel handle).
            creator_id: DB id of the Creator row.

        Returns:
            The completed ResearchRun.
        """
        run = ResearchRun(
            creator_id=creator_id,
            status="running",
            started_at=datetime.now(timezone.utc),
            config_snapshot={
                "adapter": self._adapter.platform,
                "identifier": identifier,
            },
            prompt_versions={},
            model_versions={},
        )
        self._session.add(run)
        await self._session.flush()

        await self._transition_status(creator_id, CreatorStatus.COLLECTING)

        try:
            items = await self._adapter.collect(identifier)
            await self._persist_items(items, creator_id, run.id)
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            await self._transition_status(creator_id, CreatorStatus.COLLECTED)
        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = datetime.now(timezone.utc)
            logger.exception("Collection failed for %s", identifier)
            raise
        finally:
            await self._session.flush()

        return run

    async def _persist_items(
        self,
        items: list[NormalizedContent],
        creator_id: str,
        research_run_id: str,
    ) -> None:
        content_types = set(_CONTENT_TYPE_MAP.keys())
        interaction_types = set(_INTERACTION_TYPE_MAP.keys())
        meta_types = {"channel_metadata"}

        for item in items:
            if item.content_type in meta_types:
                await self._update_platform_account(item, creator_id)

        content_items = [i for i in items if i.content_type in content_types]
        interactions = [i for i in items if i.content_type in interaction_types]
        evidence_only = [
            i for i in items
            if i.content_type not in content_types
            and i.content_type not in interaction_types
            and i.content_type not in meta_types
        ]

        content_map: dict[str, ContentItem] = {}
        for item in content_items:
            ci = await self._upsert_content_item(item, creator_id)
            content_map[item.external_id] = ci
            await self._upsert_evidence(item, research_run_id)

        for item in interactions:
            ci = await self._find_content_item_for_interaction(
                item, content_map
            )
            if ci is None:
                logger.warning(
                    "No ContentItem for interaction %s (parent=%s), skipping",
                    item.external_id,
                    item.parent_id,
                )
                continue

            await self._upsert_interaction(item, ci.id)
            await self._upsert_evidence(item, research_run_id)

        for item in evidence_only:
            await self._upsert_evidence(item, research_run_id)

    async def _upsert_content_item(
        self,
        item: NormalizedContent,
        creator_id: str,
    ) -> ContentItem:
        meta = item.metadata or {}
        result = await self._session.execute(
            select(ContentItem).where(
                ContentItem.platform == item.source_platform,
                ContentItem.external_id == item.external_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.view_count = meta.get("view_count", existing.view_count)
            existing.like_count = meta.get("like_count", existing.like_count)
            existing.comment_count = meta.get("comment_count", existing.comment_count)
            await self._session.flush()
            return existing

        ct = _CONTENT_TYPE_MAP.get(item.content_type, ContentType.VIDEO)
        ci = ContentItem(
            creator_id=creator_id,
            platform=item.source_platform,
            external_id=item.external_id,
            title=item.text[:500] if item.text else None,
            description=meta.get("description"),
            content_type=ct,
            published_at=item.timestamp,
            view_count=meta.get("view_count"),
            like_count=meta.get("like_count"),
            comment_count=meta.get("comment_count"),
            url=item.url,
            duration=meta.get("duration"),
            tags=meta.get("tags"),
            language=meta.get("language"),
            is_short=meta.get("is_short"),
        )
        self._session.add(ci)
        await self._session.flush()
        return ci

    async def _find_content_item_for_interaction(
        self,
        item: NormalizedContent,
        content_map: dict[str, ContentItem],
    ) -> ContentItem | None:
        """Find the ContentItem a comment/reply belongs to."""
        # For top-level comments, parent_id is the video external_id
        if item.content_type == "comment" and item.parent_id:
            return content_map.get(item.parent_id)

        # For replies, parent_id is the comment external_id.
        # Walk through content_map looking for any video — replies are
        # associated with the video, but we need to look up via the comment.
        # For YouTube, comment IDs contain the video ID as a prefix
        # (e.g. "Ugx..." doesn't, but we stored comment→video mapping via parent_id).
        # Fallback: check all content items.
        if item.content_type == "reply" and item.parent_id:
            # The parent_id for a reply is the comment_id.
            # We need to find which video that comment belongs to.
            # Look through all interactions with that external_id.
            result = await self._session.execute(
                select(AudienceInteraction.content_item_id).where(
                    AudienceInteraction.external_id == item.parent_id
                )
            )
            ci_id = result.scalar_one_or_none()
            if ci_id:
                result = await self._session.execute(
                    select(ContentItem).where(ContentItem.id == ci_id)
                )
                return result.scalar_one_or_none()

        return None

    async def _upsert_interaction(
        self,
        item: NormalizedContent,
        content_item_id: str,
    ) -> AudienceInteraction:
        result = await self._session.execute(
            select(AudienceInteraction).where(
                AudienceInteraction.external_id == item.external_id
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        it = _INTERACTION_TYPE_MAP.get(item.content_type, InteractionType.COMMENT)
        meta = item.metadata or {}
        interaction = AudienceInteraction(
            content_item_id=content_item_id,
            external_id=item.external_id,
            text=item.text,
            author_handle=item.author,
            author_channel_id=meta.get("author_channel_id"),
            interaction_type=it,
            posted_at=item.timestamp,
            like_count=meta.get("like_count"),
            parent_id=item.parent_id,
        )
        self._session.add(interaction)
        await self._session.flush()
        return interaction

    async def _transition_status(self, creator_id: str, status: CreatorStatus) -> None:
        result = await self._session.execute(
            select(Creator).where(Creator.id == creator_id)
        )
        creator = result.scalars().first()
        if creator:
            creator.status = status
            await self._session.flush()

    async def _update_platform_account(
        self,
        item: NormalizedContent,
        creator_id: str,
    ) -> None:
        """Update CreatorPlatformAccount with channel-level metadata."""
        meta = item.metadata or {}
        result = await self._session.execute(
            select(CreatorPlatformAccount).where(
                CreatorPlatformAccount.creator_id == creator_id,
                CreatorPlatformAccount.platform == item.source_platform,
            )
        )
        account = result.scalar_one_or_none()
        if not account:
            return
        if meta.get("subscriber_count"):
            account.subscriber_count = meta["subscriber_count"]
        if meta.get("total_view_count"):
            account.total_view_count = meta["total_view_count"]
        if meta.get("video_count"):
            account.video_count = meta["video_count"]
        if meta.get("country"):
            account.country = meta["country"]
        if meta.get("description"):
            account.description = meta["description"][:5000] if meta["description"] else None
        if meta.get("joined_at"):
            from datetime import datetime as dt
            joined = meta["joined_at"]
            if isinstance(joined, str):
                account.joined_at = dt.fromisoformat(joined.replace("Z", "+00:00"))
            else:
                account.joined_at = joined
        await self._session.flush()

    async def _upsert_evidence(
        self,
        item: NormalizedContent,
        research_run_id: str,
    ) -> Evidence:
        result = await self._session.execute(
            select(Evidence).where(
                Evidence.source_id == item.external_id,
                Evidence.source_platform == item.source_platform,
                Evidence.research_run_id == research_run_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.raw_text = item.text or ""
            await self._session.flush()
            return existing

        evidence = Evidence(
            source_type=item.content_type,
            source_id=item.external_id,
            source_platform=item.source_platform,
            raw_text=item.text or "",
            author_handle=item.author,
            source_url=item.url,
            access_method=item.access_method,
            compliance_status=item.compliance_status,
            research_run_id=research_run_id,
        )
        self._session.add(evidence)
        await self._session.flush()
        return evidence
