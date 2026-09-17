"""Multi-source niche discovery — fans a query across all niche adapters.

Given a campaign and a keyword, builds every configured niche adapter,
checks each source's health, runs the healthy ones sequentially, persists
evidence under a single NICHE_DISCOVERY run, and records per-source yields
in the research ledger.

Sources that are disconnected (circuit-breaker open) are skipped. Sources
that fail during the run have their failure recorded in the health tracker,
but the run continues with remaining sources. This is the user's
"monitored, and after continued no response they are disconnected" feature.
"""

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.config import Settings
from corp.config import settings as default_settings
from corp.core.models.campaign import Campaign
from corp.core.models.evidence import Evidence
from corp.core.models.research_query import ResearchQueryStatus
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.core.research.ledger import record_query
from corp.core.state.research_run import validate_run_type
from corp.warmstore.sync import mirror_evidence
from corp.workers.adapters.base import AdapterFamily, NormalizedContent
from corp.workers.adapters.health import SourceHealthTracker
from corp.workers.adapters.registry import build_adapter
from corp.workers.intelligence.runs import (
    PipelineStats,
    finish_run,
    start_run,
)

logger = logging.getLogger(__name__)

PIPELINE = "multi_niche_discovery"

NICHE_PLATFORMS = (
    "stackexchange",
    "searchdemand",
    "amazon_reviews",
    "marketplace",
    "hackernews",
    "wikipedia",
    "googletrends",
    "appstore",
)


def _slug(text: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()[:80] or "query"


class MultiSourceDiscovery:
    """Orchestrates niche discovery across multiple adapters.

    Usage::

        disco = MultiSourceDiscovery(session, data_path)
        run = await disco.discover(campaign_id, "python automation")
        # run.stats["per_source"] has per-adapter yields
    """

    def __init__(
        self,
        session: AsyncSession,
        data_path: str,
        cfg: Settings | None = None,
        platforms: tuple[str, ...] | None = None,
        health_tracker: SourceHealthTracker | None = None,
    ) -> None:
        self._session = session
        self._data_path = Path(data_path)
        self._cfg = cfg or default_settings
        self._platforms = platforms or NICHE_PLATFORMS
        self._health = health_tracker or SourceHealthTracker(data_path)
        self._health.load()

    async def discover(self, campaign_id: str, query: str) -> ResearchRun:
        """Fan out ``query`` across all healthy niche adapters under ``campaign_id``.

        Returns a single run whose ``stats`` include ``per_source`` with
        per-adapter yields, skip reasons, and errors. Never raises for
        individual source failures — the run continues with remaining sources.
        """
        if await self._session.get(Campaign, campaign_id) is None:
            raise ValueError(f"Campaign not found: {campaign_id}")
        validate_run_type(RunType.NICHE_DISCOVERY, creator_id=None, niche_id=None)

        run = await start_run(
            self._session,
            pipeline=PIPELINE,
            creator_id=None,
            config={"query": query, "platforms": list(self._platforms)},
            scope=RunScope.NICHE,
            run_type=RunType.NICHE_DISCOVERY,
            campaign_id=campaign_id,
        )

        stats = PipelineStats()
        per_source: dict[str, dict] = {}
        all_items: list[NormalizedContent] = []

        for platform in self._platforms:
            source_result = await self._run_source(
                run, platform, query, stats, all_items,
            )
            per_source[platform] = source_result

        self._health.save()

        if not any(s.get("status") in ("ok", "failed") for s in per_source.values()):
            # Every source was skipped (breaker open, build error, wrong
            # family): nothing was attempted, so stats would read 0/0 and the
            # run would close "completed" having done no work. Fail it and
            # name why each source was passed over.
            stats.fail(RuntimeError(
                "no niche source was available: "
                + ", ".join(f"{p}={s.get('reason')}" for p, s in per_source.items())
            ))

        archive_ref = self._archive(run.id, query, all_items)
        stats.extra.update({
            "per_source": per_source,
            "total_sources_attempted": sum(
                1 for s in per_source.values() if s.get("status") in ("ok", "failed")
            ),
            "total_sources_ok": sum(
                1 for s in per_source.values() if s.get("status") == "ok"
            ),
            "total_sources_failed": sum(
                1 for s in per_source.values() if s.get("status") == "failed"
            ),
            "total_sources_skipped": sum(
                1 for s in per_source.values() if s.get("status") == "skipped"
            ),
            "total_new_items": sum(s.get("new", 0) for s in per_source.values()),
            "total_duplicate_items": sum(s.get("duplicate", 0) for s in per_source.values()),
            "total_item_failures": sum(s.get("item_failures", 0) for s in per_source.values()),
            "total_items": len(all_items),
            "archive_reference": archive_ref,
        })

        return await finish_run(self._session, run, stats)

    async def _run_source(
        self,
        run: ResearchRun,
        platform: str,
        query: str,
        stats: PipelineStats,
        all_items: list[NormalizedContent],
    ) -> dict:
        # PipelineStats counts SOURCES here, not items: one ok()/fail()/skip()
        # per source, so the run's failure_rate answers "how many sources
        # worked". Per-item new/duplicate/failure counts live in the returned
        # dict and are aggregated into stats.extra — mixing the two axes made a
        # run with 7/8 sources dead look "completed" on one chatty survivor.
        if not self._health.is_available(platform):
            health_rec = self._health.get_record(platform)
            logger.info(
                "Skipping disconnected source %s (failures: %d, last: %s)",
                platform,
                health_rec.consecutive_failures,
                health_rec.last_error,
            )
            stats.skip()
            return {
                "status": "skipped",
                "reason": "disconnected",
                "consecutive_failures": health_rec.consecutive_failures,
            }

        try:
            adapter = build_adapter(platform, self._cfg)
        except Exception as exc:
            logger.warning("Could not build adapter for %s: %s", platform, exc)
            stats.skip()
            return {"status": "skipped", "reason": f"build_error: {exc}"}

        if adapter.family != AdapterFamily.NICHE:
            stats.skip()
            return {"status": "skipped", "reason": "not_niche_family"}

        try:
            items = await adapter.collect(query)
            self._health.record_success(platform)
        except Exception as exc:
            logger.error("Source %s failed for %r: %s", platform, query, exc)
            self._health.record_failure(platform, exc)
            await record_query(
                self._session,
                research_run_id=run.id,
                source=platform,
                query=query,
                status=ResearchQueryStatus.FAILED,
                error=str(exc)[:2000],
            )
            stats.fail(exc)
            return {
                "status": "failed",
                "error": str(exc)[:500],
                "health": self._health.get_status(platform),
            }
        finally:
            if hasattr(adapter, "close"):
                try:
                    await adapter.close()
                except Exception:
                    pass

        new = duplicate = item_failures = 0
        for item in items:
            try:
                if await self._already_have(item):
                    duplicate += 1
                    continue
                ev = _to_evidence(item, run.id)
                self._session.add(ev)
                await self._session.flush()
                await mirror_evidence([ev])
                new += 1
                all_items.append(item)
            except Exception as exc:
                logger.warning(
                    "Item %s from %s failed: %s", item.external_id, platform, exc
                )
                item_failures += 1

        stats.ok()
        await record_query(
            self._session,
            research_run_id=run.id,
            source=platform,
            query=query,
            results_seen=len(items),
            new_results=new,
            duplicate_results=duplicate,
        )

        return {
            "status": "ok",
            "results_seen": len(items),
            "new": new,
            "duplicate": duplicate,
            "item_failures": item_failures,
            "health": self._health.get_status(platform),
        }

    async def _already_have(self, item: NormalizedContent) -> bool:
        result = await self._session.execute(
            select(Evidence.id)
            .where(
                Evidence.source_platform == item.source_platform,
                Evidence.source_id == item.external_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    def _archive(
        self, run_id: str, query: str, items: list[NormalizedContent]
    ) -> str | None:
        if not items:
            return None
        relative = Path("discovery") / run_id / f"multi__{_slug(query)}.jsonl"
        target = self._data_path / relative
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8") as fh:
                for item in items:
                    fh.write(json.dumps(item.model_dump(mode="json"), ensure_ascii=False))
                    fh.write("\n")
        except OSError as exc:
            logger.warning("Multi-discovery archive not written (%s): %s", target, exc)
            return None
        return relative.as_posix()

    def health_summary(self) -> dict:
        return self._health.summary()


def _to_evidence(item: NormalizedContent, run_id: str) -> Evidence:
    return Evidence(
        source_type=item.content_type,
        source_id=item.external_id,
        source_platform=item.source_platform,
        raw_text=item.text,
        author_handle=item.author,
        source_url=item.url,
        access_method=item.access_method,
        compliance_status=item.compliance_status,
        research_run_id=run_id,
    )
