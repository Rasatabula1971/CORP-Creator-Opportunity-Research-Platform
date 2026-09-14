"""Niche discovery, light (§15 Stage A): one source → stored evidence.

Given a campaign and a query (for Reddit, a subreddit — a community is an
observable market signal), run the adapter once, persist every result as
append-only Evidence under a NICHE_DISCOVERY ResearchRun, record the query
and its yield in the research ledger, and archive the raw items under
CORP_DATA_PATH (§24).

Deliberately not here (later slices): multiple sources, candidate-niche
generation, any scoring, any creator discovery. No LLM is called.
"""

import json
import logging
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.evidence import Evidence
from corp.core.models.research_query import ResearchQueryStatus
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.core.research.ledger import record_query
from corp.core.state.research_run import validate_run_type
from corp.workers.adapters.base import NormalizedContent, SourceAdapter
from corp.workers.intelligence.runs import (
    PipelineStats,
    fail_run,
    finish_run,
    start_run,
)

logger = logging.getLogger(__name__)

PIPELINE = "niche_discovery"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()[:80] or "query"


class NicheDiscoveryCollector:
    def __init__(self, adapter: SourceAdapter, session: AsyncSession, data_path: str) -> None:
        self._adapter = adapter
        self._session = session
        self._data_path = Path(data_path)

    async def discover(self, campaign_id: str, query: str) -> ResearchRun:
        """One query against one source, under ``campaign_id``. Returns the run.

        Never raises for a source or item failure — it returns the run with
        ``status`` set (``failed`` / ``partial`` / ``completed``). A failed
        search is still research memory (§13): the FAILED ledger row and the
        failed run must reach the database, and they only do if the caller's
        normal commit runs. An unknown campaign is the one hard error.
        """
        if await self._session.get(Campaign, campaign_id) is None:
            raise ValueError(f"Campaign not found: {campaign_id}")
        validate_run_type(RunType.NICHE_DISCOVERY, creator_id=None, niche_id=None)

        source = self._adapter.platform
        run = await start_run(
            self._session,
            pipeline=PIPELINE,
            creator_id=None,
            config={"source": source, "query": query},
            scope=RunScope.NICHE,
            run_type=RunType.NICHE_DISCOVERY,
            campaign_id=campaign_id,
        )

        try:
            items = await self._adapter.collect(query)
        except Exception as exc:
            logger.error("discovery source %s failed for %r: %s", source, query, exc)
            await record_query(
                self._session,
                research_run_id=run.id,
                source=source,
                query=query,
                status=ResearchQueryStatus.FAILED,
                error=str(exc)[:2000],
            )
            await fail_run(self._session, run, exc)
            return run

        stats = PipelineStats()
        new = duplicate = 0
        for item in items:
            try:
                if await self._already_have(item):
                    stats.skip()
                    duplicate += 1
                    continue
                self._session.add(self._evidence(item, run.id))
                await self._session.flush()
                stats.ok()
                new += 1
            except Exception as exc:  # one bad item must not sink the run
                logger.warning("discovery item %s failed: %s", item.external_id, exc)
                stats.fail(exc)

        archive_ref = self._archive(run.id, source, query, items)
        stats.extra.update(
            {"results_seen": len(items), "new_results": new, "duplicate_results": duplicate}
        )
        await record_query(
            self._session,
            research_run_id=run.id,
            source=source,
            query=query,
            results_seen=len(items),
            new_results=new,
            duplicate_results=duplicate,
            archive_reference=archive_ref,
        )
        return await finish_run(self._session, run, stats)

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

    @staticmethod
    def _evidence(item: NormalizedContent, run_id: str) -> Evidence:
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

    def _archive(
        self, run_id: str, source: str, query: str, items: list[NormalizedContent]
    ) -> str | None:
        """Write the raw normalized items as JSONL; return a data-path-relative
        reference. Non-fatal: the DB evidence is the durable record, the archive
        is the bulk copy (§24)."""
        relative = Path("discovery") / run_id / f"{source}__{_slug(query)}.jsonl"
        target = self._data_path / relative
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8") as fh:
                for item in items:
                    fh.write(json.dumps(item.model_dump(mode="json"), ensure_ascii=False))
                    fh.write("\n")
        except OSError as exc:
            logger.warning("discovery archive not written (%s): %s", target, exc)
            return None
        return relative.as_posix()
