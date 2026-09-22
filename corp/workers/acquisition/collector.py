"""Acquisition orchestrator — adapter output → DB rows with evidence chain."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.content import AudienceInteraction, ContentItem, ContentType, InteractionType
from corp.core.models.creator import CreatorPlatformAccount, CreatorStatus
from corp.core.models.evidence import Evidence, EvidenceOrigin, require_evidence_type
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
    "question": ContentType.THREAD,
    "review": ContentType.ARTICLE,
}

_INTERACTION_TYPE_MAP = {
    "comment": InteractionType.COMMENT,
    "reply": InteractionType.REPLY,
}


_EXTRA_KEYS = ("commerce_signals", "tags", "music", "domain", "duration", "flair", "subreddit")


def _content_extra(meta: dict[str, Any]) -> dict[str, Any] | None:
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
        for item in videos:
            ci = await self._upsert_content_item(item, creator_id)
            content_map[item.external_id] = ci
            await self._create_evidence(item, research_run_id)
            await self._snapshot_content(ci, item, research_run_id)

        for item in comments:
            parent_ci: ContentItem | None = await self._find_content_item_for_interaction(
                item, content_map
            )
            if parent_ci is None:
                # Reviews and questions are standalone — persist evidence even
                # without a parent ContentItem so the intelligence pipeline can
                # still use them.
                await self._create_evidence(item, research_run_id)
                orphaned += 1
                continue

            await self._upsert_interaction(item, parent_ci.id)
            await self._create_evidence(item, research_run_id)

        for item in captions:
            await self._create_evidence(item, research_run_id)

        # Niche-family adapters emit content types (listing, project, trend,
        # interest, pageview_trend, creator_page) that don't map to content
        # items or interactions.  Persist their evidence so downstream
        # pipelines can still use the raw text.
        unhandled = [
            i
            for i in items
            if i.content_type not in _CONTENT_TYPE_MAP
            and i.content_type not in _INTERACTION_TYPE_MAP
            and i.content_type not in ("caption", "profile")
        ]
        for item in unhandled:
            logger.info(
                "Unhandled content_type %r from %s — persisting evidence only",
                item.content_type,
                item.source_platform,
            )
            await self._create_evidence(item, research_run_id)

        return {
            "content_items": len(videos),
            "interactions": len(comments) - orphaned,
            "captions": len(captions),
            "profiles": len(profiles),
            "orphaned_interactions": orphaned,
            "evidence_only": len(unhandled),
        }

    async def _record_profile(
        self, item: NormalizedContent, creator_id: str, research_run_id: str
    ) -> None:
        """Update the platform account's follower count and append a snapshot."""
        meta = item.metadata or {}
        followers = _int_or_none(meta.get("follower_count"))
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
                account.subscriber_count = followers
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
                        setattr(account, field, _int_or_none(value))
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
            follower_count=followers,
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
        """Find the ContentItem a comment/reply/question/review belongs to."""
        # Top-level interactions: parent_id, when set, is the content item's
        # external_id directly. "question"/"review" are declared as supported
        # interaction types (see _INTERACTION_TYPE_MAP) alongside "comment", so
        # they must be matched the same way or they're silently orphaned.
        if item.content_type in ("comment", "question", "review") and item.parent_id:
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
        await mirror_interactions([interaction])
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
            evidence_type=require_evidence_type(item.source_platform),
            origin=EvidenceOrigin.OBSERVATION,
        )
        self._session.add(evidence)
        await self._session.flush()
        await mirror_evidence([evidence])
        return evidence
