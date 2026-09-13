"""Acquisition orchestrator — adapter output → DB rows with evidence chain."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.content import AudienceInteraction, ContentItem, ContentType, InteractionType
from corp.core.models.creator import CreatorPlatformAccount, CreatorStatus
from corp.core.models.evidence import Evidence
from corp.core.models.metrics import MetricsSnapshot
from corp.core.models.workflow import ResearchRun
from corp.workers.adapters.base import NormalizedContent, SourceAdapter
from corp.workers.intelligence.runs import (
    PipelineStats,
    fail_run,
    finish_run,
    stage,
    start_run,
)

logger = logging.getLogger(__name__)

_CONTENT_TYPE_MAP = {
    "video": ContentType.VIDEO,
    "post": ContentType.POST,
    "short": ContentType.SHORT,
    "reel": ContentType.REEL,
    "article": ContentType.ARTICLE,
    "story": ContentType.STORY,
    "thread": ContentType.THREAD,
    "page": ContentType.PAGE,
}

_INTERACTION_TYPE_MAP = {
    "comment": InteractionType.COMMENT,
    "reply": InteractionType.REPLY,
    "question": InteractionType.QUESTION,
    "review": InteractionType.REVIEW,
}


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


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
        run = await start_run(
            self._session,
            pipeline="collect",
            creator_id=creator_id,
            config={"adapter": self._adapter.platform, "identifier": identifier},
        )
        stats = PipelineStats()

        try:
            async with stage(
                self._session,
                creator_id,
                working=CreatorStatus.COLLECTING,
                done=CreatorStatus.COLLECTED,
            ):
                items = await self._adapter.collect(identifier)
                counts = await self._persist_items(items, creator_id, run.id)
                stats.extra.update(counts)
                stats.ok()
                await finish_run(self._session, run, stats)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception("Collection failed for %s", identifier)
            raise

        return run

    async def _persist_items(
        self,
        items: list[NormalizedContent],
        creator_id: str,
        research_run_id: str,
    ) -> dict[str, int]:
        # Any adapter content type with a ContentType mapping is a content item
        # (video, post, short, ...); comments and replies hang off those.
        videos = [i for i in items if i.content_type in _CONTENT_TYPE_MAP]
        comments = [i for i in items if i.content_type in _INTERACTION_TYPE_MAP]
        captions = [i for i in items if i.content_type == "caption"]
        profiles = [i for i in items if i.content_type == "profile"]
        orphaned = 0

        for item in profiles:
            await self._record_profile(item, creator_id, research_run_id)

        content_map: dict[str, ContentItem] = {}
        for item in videos:
            ci = await self._upsert_content_item(item, creator_id)
            content_map[item.external_id] = ci
            await self._create_evidence(item, research_run_id)
            await self._snapshot_content(ci, item, research_run_id)

        for item in comments:
            ci = await self._find_content_item_for_interaction(
                item, content_map
            )
            if ci is None:
                logger.warning(
                    "No ContentItem for interaction %s (parent=%s), skipping",
                    item.external_id,
                    item.parent_id,
                )
                orphaned += 1
                continue

            await self._upsert_interaction(item, ci.id)
            await self._create_evidence(item, research_run_id)

        for item in captions:
            await self._create_evidence(item, research_run_id)

        return {
            "content_items": len(videos),
            "interactions": len(comments) - orphaned,
            "captions": len(captions),
            "profiles": len(profiles),
            "orphaned_interactions": orphaned,
        }

    async def _record_profile(
        self, item: NormalizedContent, creator_id: str, research_run_id: str
    ) -> None:
        """Update the platform account's follower count and append a snapshot."""
        meta = item.metadata or {}
        followers = meta.get("follower_count")
        result = await self._session.execute(
            select(CreatorPlatformAccount).where(
                CreatorPlatformAccount.creator_id == creator_id,
                CreatorPlatformAccount.platform == item.source_platform,
            )
        )
        account = result.scalars().first()
        if account is None:
            logger.info(
                "No %s account row for creator %s; profile snapshot stored without account link",
                item.source_platform,
                creator_id,
            )
        else:
            if followers is not None:
                account.subscriber_count = int(followers)
            if meta.get("handle") and not account.external_id:
                account.external_id = str(meta["handle"])[:255]

        self._session.add(
            MetricsSnapshot(
                research_run_id=research_run_id,
                platform_account_id=account.id if account else None,
                follower_count=int(followers) if followers is not None else None,
                extra={
                    "platform": item.source_platform,
                    "display_name": meta.get("display_name"),
                    "video_count": meta.get("video_count"),
                },
            )
        )
        await self._create_evidence(item, research_run_id)
        await self._session.flush()

    async def _snapshot_content(
        self, ci: ContentItem, item: NormalizedContent, research_run_id: str
    ) -> None:
        meta = item.metadata or {}
        # Keep the latest counts on the row; the snapshot preserves history.
        for field in ("view_count", "like_count", "comment_count"):
            value = meta.get(field)
            if value is not None:
                setattr(ci, field, int(value))
        self._session.add(
            MetricsSnapshot(
                research_run_id=research_run_id,
                content_item_id=ci.id,
                view_count=_int_or_none(meta.get("view_count")),
                like_count=_int_or_none(meta.get("like_count")),
                comment_count=_int_or_none(meta.get("comment_count")),
                share_count=_int_or_none(meta.get("share_count")),
            )
        )

    async def _upsert_content_item(
        self,
        item: NormalizedContent,
        creator_id: str,
    ) -> ContentItem:
        result = await self._session.execute(
            select(ContentItem).where(
                ContentItem.platform == item.source_platform,
                ContentItem.external_id == item.external_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        ct = _CONTENT_TYPE_MAP.get(item.content_type, ContentType.VIDEO)
        meta = item.metadata or {}
        ci = ContentItem(
            creator_id=creator_id,
            platform=item.source_platform,
            external_id=item.external_id,
            title=(meta.get("title") or item.text or "")[:500] or None,
            description=(meta.get("description") or None),
            content_type=ct,
            published_at=item.timestamp,
            view_count=meta.get("view_count"),
            like_count=meta.get("like_count"),
            comment_count=meta.get("comment_count"),
            url=item.url,
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
            parent_result = await self._session.execute(
                select(AudienceInteraction.content_item_id)
                .where(AudienceInteraction.external_id == item.parent_id)
                .limit(1)
            )
            ci_id = parent_result.scalar_one_or_none()
            if ci_id:
                return await self._session.get(ContentItem, ci_id)

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
            interaction_type=it,
            posted_at=item.timestamp,
            like_count=meta.get("like_count"),
            parent_id=item.parent_id,
        )
        self._session.add(interaction)
        await self._session.flush()
        return interaction

    async def _create_evidence(
        self,
        item: NormalizedContent,
        research_run_id: str,
    ) -> Evidence:
        evidence = Evidence(
            source_type=item.content_type,
            source_id=item.external_id,
            source_platform=item.source_platform,
            raw_text=item.text[:10000] if item.text else "",
            author_handle=item.author,
            source_url=item.url,
            access_method=item.access_method,
            compliance_status=item.compliance_status,
            research_run_id=research_run_id,
        )
        self._session.add(evidence)
        await self._session.flush()
        return evidence
