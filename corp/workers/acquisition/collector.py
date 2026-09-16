"""Acquisition orchestrator — adapter output → DB rows with evidence chain."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.content import AudienceInteraction, ContentItem, ContentType, InteractionType
from corp.core.models.creator import CreatorPlatformAccount, CreatorStatus
from corp.core.models.evidence import Evidence
from corp.core.models.metrics import MetricsSnapshot
from corp.core.models.workflow import ResearchRun
from corp.warmstore.sync import (
    mirror_content_items,
    mirror_evidence,
    mirror_interactions,
    mirror_metrics,
)
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


_EXTRA_KEYS = ("commerce_signals", "tags", "music", "domain", "duration", "flair", "subreddit")


def _content_extra(meta: dict) -> dict | None:
    """Whitelist adapter metadata that scoring or the dossier can use later."""
    extra = {k: meta[k] for k in _EXTRA_KEYS if meta.get(k) not in (None, "", [], {})}
    links = meta.get("links")
    if isinstance(links, list):
        extra["link_kinds"] = sorted({k for link in links for k in link.get("kinds", [])})
        extra["commerce_links"] = [
            {"url": link["url"], "kinds": link["kinds"]} for link in links if link.get("kinds")
        ][:20]
    return extra or None


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

        await self._transition_status(creator_id, CreatorStatus.COLLECTING)

        try:
            async with stage(
                self._session,
                creator_id,
                working=CreatorStatus.COLLECTING,
                done=CreatorStatus.COLLECTED,
                run=run,
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
        for item in content_items:
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
            await self._upsert_evidence(item, research_run_id)

        for item in evidence_only:
            await self._upsert_evidence(item, research_run_id)

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
            # Populate main-lineage typed channel enrichment columns from adapter
            # metadata when available. MetricsSnapshot below still captures the
            # full time-series; these are the "latest value" cheap-read columns.
            for field, key in (
                ("total_view_count", "total_view_count"),
                ("video_count", "video_count"),
                ("country", "country"),
                ("description", "description"),
            ):
                value = meta.get(key)
                if value is not None:
                    if field in ("total_view_count", "video_count"):
                        setattr(account, field, int(value))
                    else:
                        # description / country are strings; truncate country to fit.
                        as_str = str(value)
                        if field == "country":
                            as_str = as_str[:10]
                        setattr(account, field, as_str)
            joined_at = meta.get("joined_at")
            if joined_at is not None and account.joined_at is None:
                account.joined_at = joined_at

        snapshot = MetricsSnapshot(
            research_run_id=research_run_id,
            platform_account_id=account.id if account else None,
            follower_count=int(followers) if followers is not None else None,
            extra={
                "platform": item.source_platform,
                "display_name": meta.get("display_name"),
                "video_count": meta.get("video_count"),
            },
        )
        self._session.add(snapshot)
        await self._create_evidence(item, research_run_id)
        await self._session.flush()
        await mirror_metrics([snapshot])

    async def _snapshot_content(
        self, ci: ContentItem, item: NormalizedContent, research_run_id: str
    ) -> None:
        meta = item.metadata or {}
        # Keep the latest counts and metadata on the row; the snapshot preserves history.
        ci.extra = _content_extra(meta) or ci.extra
        for field in ("view_count", "like_count", "comment_count"):
            value = meta.get(field)
            if value is not None:
                setattr(ci, field, int(value))
        # Populate main-lineage typed video enrichment columns from adapter metadata.
        # Nullable — an adapter that doesn't supply the field leaves it as-is.
        duration = meta.get("duration")
        if duration is not None:
            ci.duration = int(duration)
        tags = meta.get("tags")
        if tags is not None:
            ci.tags = list(tags) if not isinstance(tags, list) else tags
        language = meta.get("language")
        if language is not None:
            ci.language = str(language)[:10]
        is_short = meta.get("is_short")
        if is_short is not None:
            ci.is_short = bool(is_short)
        snapshot = MetricsSnapshot(
            research_run_id=research_run_id,
            content_item_id=ci.id,
            view_count=_int_or_none(meta.get("view_count")),
            like_count=_int_or_none(meta.get("like_count")),
            comment_count=_int_or_none(meta.get("comment_count")),
            share_count=_int_or_none(meta.get("share_count")),
        )
        self._session.add(snapshot)
        # Flush before mirroring so the DB fills id and captured_at (server
        # default); mirroring an unflushed row writes captured_at=None, which the
        # warm store's NOT NULL column rejects — silently, so content metrics
        # never reached the warm store. _snapshot_account already flushes first.
        await self._session.flush()
        await mirror_metrics([snapshot])

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
            title=(meta.get("title") or item.text or "")[:500] or None,
            description=(meta.get("description") or None),
            content_type=ct,
            published_at=item.timestamp,
            view_count=meta.get("view_count"),
            like_count=meta.get("like_count"),
            comment_count=meta.get("comment_count"),
            url=item.url,
            extra=_content_extra(meta),
        )
        self._session.add(ci)
        await self._session.flush()
        await mirror_content_items([ci])
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
            author_channel_id=meta.get("author_channel_id"),
            interaction_type=it,
            posted_at=item.timestamp,
            like_count=meta.get("like_count"),
            parent_id=item.parent_id,
        )
        self._session.add(interaction)
        await self._session.flush()
        await mirror_interactions([interaction])
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
        await mirror_evidence([evidence])
        return evidence
