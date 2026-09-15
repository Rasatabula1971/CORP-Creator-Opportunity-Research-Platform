"""Research orchestrator — runs every stage for one creator, in order.

    collect (per confirmed platform account)
    → intelligence (extraction + topics)
    → clustering
    → intent
    → scoring
    → dossier render
    → HUMAN_REVIEW

Each stage moves the creator through the state machine. A failing stage
leaves the creator at the status it had before that stage and stops the run.
Whether it raised or finished with status ``failed``, its run row is kept
(committed) — a failed run is research memory too.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.config import Settings
from corp.config import settings as default_settings
from corp.core.models.creator import Creator, CreatorPlatformAccount, CreatorStatus
from corp.core.models.workflow import ResearchRun
from corp.core.state.transitions import advance
from corp.workers.acquisition.collector import AcquisitionCollector
from corp.workers.adapters.registry import build_adapter
from corp.workers.dossier.generator import DossierGenerator
from corp.workers.intelligence.cluster_pipeline import ClusterPipeline
from corp.workers.intelligence.embeddings import Embedder
from corp.workers.intelligence.intent_pipeline import IntentPipeline
from corp.workers.intelligence.pipeline import IntelligencePipeline
from corp.workers.intelligence.scoring_pipeline import ScoringPipeline
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class ResearchReport:
    creator_id: str
    runs: list[ResearchRun] = field(default_factory=list)
    final_status: str = ""
    dossier_html: str | None = None

    def summary(self) -> str:
        lines = [f"creator={self.creator_id} status={self.final_status}"]
        for run in self.runs:
            pipeline = (run.config_snapshot or {}).get("pipeline", "?")
            lines.append(f"  {pipeline:<13} {run.status:<10} run={run.id}")
        return "\n".join(lines)


class ResearchOrchestrator:
    def __init__(
        self,
        session: AsyncSession,
        provider: LLMProvider,
        embedder_factory: Callable[[], Embedder],
        cfg: Settings | None = None,
    ) -> None:
        self._session = session
        self._provider = provider
        self._embedder_factory = embedder_factory
        self._cfg = cfg or default_settings

    async def run(self, creator_id: str, *, skip_collect: bool = False) -> ResearchReport:
        creator = await self._session.get(Creator, creator_id)
        if creator is None:
            raise ValueError(f"Creator not found: {creator_id}")

        report = ResearchReport(creator_id=creator_id)
        commit = self._session.commit

        async def step(run: ResearchRun) -> bool:
            """Record a stage's run and commit it. True when the sequence must stop:
            a stage that failed outright produced nothing for the next one, and
            finish_run no longer raises to say so — the status is the signal."""
            report.runs.append(run)
            await commit()
            if run.status == "failed":
                pipeline = (run.config_snapshot or {}).get("pipeline", "?")
                logger.warning(
                    "stage %s failed for creator %s; stopping research: %s",
                    pipeline,
                    creator_id,
                    run.error_message,
                )
                report.final_status = creator.status.value
                return True
            return False

        if not skip_collect:
            for account in await self._accounts(creator_id):
                adapter = build_adapter(account.platform, self._cfg)
                try:
                    run = await AcquisitionCollector(adapter, self._session).collect_creator_data(
                        account.handle, creator_id
                    )
                finally:
                    close = getattr(adapter, "close", None)
                    if close is not None:
                        await close()
                if await step(run):
                    return report

        if await step(
            await IntelligencePipeline(
                self._provider, self._session, self._cfg.pipeline_max_failure_rate
            ).run(creator_id)
        ):
            return report

        if await step(
            await ClusterPipeline(self._embedder_factory(), self._session).run(creator_id)
        ):
            return report

        if await step(
            await IntentPipeline(
                self._provider,
                self._session,
                rules_path=self._cfg.intent_rules_path,
                max_failure_rate=self._cfg.pipeline_max_failure_rate,
            ).run(creator_id)
        ):
            return report

        if await step(
            await ScoringPipeline(self._session, self._cfg.scoring_rules_path).run(creator_id)
        ):
            return report

        await advance(self._session, creator, CreatorStatus.RESEARCH_COMPLETE)
        report.dossier_html = await DossierGenerator(
            self._session, self._cfg.scoring_rules_path
        ).generate(creator_id)
        await advance(self._session, creator, CreatorStatus.DOSSIER_GENERATED)
        await advance(self._session, creator, CreatorStatus.HUMAN_REVIEW)
        await commit()

        report.final_status = creator.status.value
        return report

    async def _accounts(self, creator_id: str) -> list[CreatorPlatformAccount]:
        result = await self._session.execute(
            select(CreatorPlatformAccount).where(CreatorPlatformAccount.creator_id == creator_id)
        )
        accounts = list(result.scalars().all())
        if not accounts:
            raise ValueError(
                f"Creator {creator_id} has no platform accounts; add one before researching"
            )
        return accounts
