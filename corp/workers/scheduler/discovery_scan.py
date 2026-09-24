"""The autonomous discovery crawler — CORP1 Step 1 with no user input.

One pass runs the entire frozen product flow unattended: Level 0 trend
scan → recursive niche drill-down per seed topic → canonicalize → verify
→ estimate-ecosystem → qualify → select → onboard → research (collect →
intelligence → cluster → intent → score → dossier, ending at
``HUMAN_REVIEW``). The only human touchpoint is the decision gate on the
dossiers this produces (Reject / Research More / Watch / Approve) — a
person never clicks through the intermediate campaign-pipeline stages by
hand for a pass this function ran; those per-stage endpoints
(``POST /campaigns/{id}/{stage}``) exist for re-running one stage by hand
(e.g. after fixing a rules file), not as a required part of the flow.

**Off by default.** ``settings.discovery_enabled`` gates the scheduler, so
installing this does not silently start burning LLM/YouTube quota. The
manual trigger (``POST /discovery/run``) works either way, which is the
intended way to run one pass end to end before switching the timer on —
be aware that a pass which drills anything will, unattended, go all the
way to onboarding creators and researching them (real API/LLM spend), not
stop for review before that.

**Idempotence across passes** is the research registry's job, not a lock
here: :func:`~corp.workers.intelligence.niche_discovery.registry_fresh`
drops any topic still inside its 90-day window, so a pass that runs twice
in a day does not re-drill the same tree.

The loop mechanics (backoff on consecutive failures, a tick that can never
kill the task, provider-cooldown deferral) mirror
:class:`~corp.workers.scheduler.registry_rescan.RegistryRescanScheduler`
on purpose — two schedulers in one process behaving differently under
failure would be a trap.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from corp.config import Settings, settings
from corp.core.models.campaign import Campaign, CampaignStatus
from corp.workers.intelligence.niche_discovery import DiscoveryConfig, RecursiveNicheDiscovery
from corp.workers.intelligence.niche_qualification import NicheQualifier
from corp.workers.intelligence.trend_scan import (
    DEFAULT_BROAD_TOPICS_PATH,
    SeedTopic,
    TrendScanConfig,
    TrendScanner,
    TrendScanStats,
)
from corp.workers.providers.capabilities import TrendProvider
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)

# Daily. Each pass costs a recursive LLM drill per seed topic, so this is
# a cost lever as much as a freshness one.
DEFAULT_INTERVAL_SECONDS = 86_400

# The standing campaign autonomous passes attach to. One campaign rather
# than one per pass: the niche tree and its registry are cumulative, and a
# campaign per night would shatter the dashboard into empty shells.
AUTONOMOUS_CAMPAIGN_NAME = "Autonomous discovery"
# Machine identity for that campaign, unique-constrained at the database
# level (Campaign.slug) — unlike AUTONOMOUS_CAMPAIGN_NAME, which is
# editable display text a person could rename, breaking a name-based
# lookup silently.
AUTONOMOUS_CAMPAIGN_SLUG = "autonomous-discovery"


class DiscoveryDeferredError(Exception):
    """Skip this tick without counting it as a failure (providers cooling)."""


@dataclass
class DiscoveryPassStats:
    """Outcome of one pass, for the log line and the API response."""

    topics_selected: int = 0
    topics_drilled: int = 0
    topics_failed: int = 0
    qualified: bool = False
    campaign_id: str | None = None
    scan: dict[str, Any] = field(default_factory=dict)
    topics: list[dict[str, Any]] = field(default_factory=list)
    # Outcome of canonicalize/verify/estimate_ecosystem/qualify/select/
    # onboard/research_campaign, keyed by stage name -- see
    # _advance_campaign_to_gate. Each entry is either {"run_id", "status"}
    # on success or {"status": "failed", "error": <safe message>} on a
    # stage that raised (never the exception's own text — this dict flows
    # into the job's result, readable from GET /jobs/{job_id}).
    pipeline: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "topics_selected": self.topics_selected,
            "topics_drilled": self.topics_drilled,
            "topics_failed": self.topics_failed,
            "qualified": self.qualified,
            "campaign_id": self.campaign_id,
            "scan": self.scan,
            "topics": self.topics,
            "pipeline": self.pipeline,
        }


def momentum_readiness(cfg: Settings) -> tuple[str, bool, str | None]:
    """(source, available, why-not) for the configured momentum source.

    No network: this only checks that the source's prerequisites exist, so
    the status endpoint can call it on every read.
    """
    source = cfg.discovery_momentum_source
    if source == "none":
        return source, False, "momentum disabled; topics are ranked by rotation"
    if source == "youtube":
        if not cfg.youtube_api_key:
            return source, False, "YOUTUBE_API_KEY is not set; topics are ranked by rotation"
        return source, True, None
    # googletrends: the trending RSS needs nothing, but a per-topic interest
    # series needs pytrends. Without it most catalogue topics match nothing.
    try:
        import pytrends  # noqa: F401
    except ImportError:
        return (
            source,
            False,
            "pytrends is not installed; Google Trends can only keyword-match the "
            "trending feed, which rarely contains catalogue topics",
        )
    return source, True, None


def build_momentum_provider(cfg: Settings, region: str) -> TrendProvider | None:
    """The TrendProvider the scanner ranks with, or None to rank by rotation.

    One place for both the scheduler and the manual trigger to decide, so
    the two cannot silently disagree about where momentum comes from.
    """
    source = cfg.discovery_momentum_source
    if source == "none":
        return None
    if source == "youtube":
        if not cfg.youtube_api_key:
            logger.info("Discovery momentum: YOUTUBE_API_KEY not set; ranking by rotation")
            return None
        from corp.workers.adapters.youtube_trends import YouTubeTrendsAdapter

        return YouTubeTrendsAdapter(
            api_key=cfg.youtube_api_key,
            region=region,
            daily_quota=cfg.youtube_daily_quota_units,
            requests_per_second=cfg.youtube_requests_per_second,
        )
    from corp.workers.adapters.registry import build_adapter

    adapter = build_adapter("googletrends", cfg)
    if isinstance(adapter, TrendProvider):
        return adapter
    raise TypeError(f"googletrends adapter is not a TrendProvider: {type(adapter).__name__}")


async def get_or_create_autonomous_campaign(
    session: AsyncSession, name: str = AUTONOMOUS_CAMPAIGN_NAME
) -> Campaign:
    """The standing campaign for unattended passes, created on first use.

    Matched only by slug (Campaign.slug, unique-constrained — see
    migration 8fb35dc16e35), which is what makes two near-simultaneous
    passes safe: only one of two concurrent inserts can win that
    constraint, and the loser fetches the winner's row instead of leaving
    a duplicate campaign behind. A row that already existed when that
    migration ran was backfilled by the migration itself (matched
    case-insensitively on name, once, at migration time) — this function
    deliberately does NOT repeat that name match at runtime: a person is
    free to create their own campaign named "Autonomous discovery" for
    unrelated work, and adopting it by name here would silently
    repurpose it (and everything already in it) as the standing target
    for every future unattended pass.

    Must be the first thing this function's caller does with ``session``:
    losing the race rolls the whole session back (a failed flush leaves
    it unusable until Session.rollback() is called — see the IntegrityError
    branch below), which would discard any other pending work already
    flushed on it. Both current callers open a fresh session for exactly
    this call, so that's never a concern in practice.
    """
    result = await session.execute(
        select(Campaign).where(Campaign.slug == AUTONOMOUS_CAMPAIGN_SLUG).limit(1)
    )
    campaign = result.scalar_one_or_none()
    if campaign is not None:
        return campaign

    campaign = Campaign(
        name=name,
        slug=AUTONOMOUS_CAMPAIGN_SLUG,
        status=CampaignStatus.ACTIVE,
        started_at=datetime.now(UTC),
    )
    session.add(campaign)
    try:
        await session.flush()
    except IntegrityError:
        # Lost the race: a concurrent call already inserted the row with
        # this slug between our select above and this flush. A failed
        # flush leaves the session unusable until it's rolled back (see
        # the docstring above on why that's safe here) — then fetch the
        # winner's row instead of failing the pass.
        await session.rollback()
        result = await session.execute(
            select(Campaign).where(Campaign.slug == AUTONOMOUS_CAMPAIGN_SLUG).limit(1)
        )
        return result.scalar_one()
    logger.info("Created the autonomous discovery campaign %s", campaign.id)
    return campaign


async def run_discovery_pass(
    session: AsyncSession,
    provider: LLMProvider,
    *,
    trend_provider: TrendProvider | None = None,
    niche_rules_path: str = "rules/niche_discovery_prompt.yaml",
    qualification_rules_path: str = "rules/niche_qualification.yaml",
    topics_per_pass: int | None = None,
    campaign_id: str | None = None,
    topics: list[str] | None = None,
    broad_topics_path: str = DEFAULT_BROAD_TOPICS_PATH,
) -> DiscoveryPassStats:
    """One full pass. Caller owns the transaction.

    ``topics`` overrides the trend scan — that is the user-suggested entry
    point the spec asks for ("accepted as an alternate entry point
    alongside autonomous discovery"), taking the identical path through
    the drill engine rather than a parallel one, so a hand-picked niche
    produces exactly the same evidence, lineage and dossier as a
    discovered one.
    """
    stats = DiscoveryPassStats()

    if campaign_id is None:
        campaign = await get_or_create_autonomous_campaign(session)
        campaign_id = campaign.id
    stats.campaign_id = campaign_id

    if topics:
        seeds = [SeedTopic(topic=t.strip().lower(), momentum=None, reason="user_supplied")
                 for t in topics if t and t.strip()]
        scan_stats = TrendScanStats(catalogue=len(seeds), selected=len(seeds))
    else:
        scanner = TrendScanner(
            session,
            trend_provider=trend_provider,
            config=TrendScanConfig.from_rules(broad_topics_path),
            niche_rules_path=niche_rules_path,
        )
        seeds, scan_stats = await scanner.scan(topics_per_pass)

    stats.scan = scan_stats.as_dict()
    stats.topics_selected = len(seeds)
    if not seeds:
        logger.info("Discovery pass: no topics due; nothing to do")
        return stats

    discovery = RecursiveNicheDiscovery(session, provider, niche_rules_path)
    for seed in seeds:
        try:
            run = await discovery.discover(campaign_id, seed.topic)
        except Exception:  # noqa: BLE001 — one topic must not sink the pass
            stats.topics_failed += 1
            stats.topics.append(
                {
                    "topic": seed.topic,
                    "reason": seed.reason,
                    "momentum": seed.momentum,
                    "status": "failed",
                    # Not str(exc): this dict flows into the job's result,
                    # readable from GET /jobs/{job_id}, and an adapter
                    # exception can carry filesystem paths, URLs, or
                    # provider/connection details (same rule as
                    # /discovery/status — see routes_ops.py). Full detail
                    # goes to the log only, via logger.exception below.
                    "error": "drilling this topic failed; details in the server log",
                }
            )
            logger.exception("Discovery pass: drilling %r failed", seed.topic)
            continue
        # A drill that produced nothing (every evidence source errored for
        # this keyword) finishes via finish_run/fail_run without raising --
        # status is the signal, same convention as ResearchOrchestrator.step.
        # Counting that as "drilled" would run the whole downstream chain
        # (canonicalize..research) believing this topic contributed
        # something, and report a clean "qualified: true" over what was
        # really a total source outage for it.
        if run.status == "failed":
            stats.topics_failed += 1
        else:
            stats.topics_drilled += 1
        stats.topics.append(
            {
                "topic": seed.topic,
                "reason": seed.reason,
                "momentum": seed.momentum,
                "status": run.status,
                "run_id": run.id,
            }
        )

    # Run the rest of the campaign pipeline once for the campaign rather
    # than per topic: qualification (and everything after it) ranks/acts
    # on the campaign's niches against each other, so running it after
    # every drill would work against a half-built field.
    if stats.topics_drilled:
        stats.pipeline = await _advance_campaign_to_gate(
            session, provider, campaign_id, niche_rules_path, qualification_rules_path,
        )
        stats.qualified = "run_id" in stats.pipeline.get("qualify", {})

    logger.info(
        "Discovery pass: selected=%d drilled=%d failed=%d qualified=%s campaign=%s",
        stats.topics_selected,
        stats.topics_drilled,
        stats.topics_failed,
        stats.qualified,
        campaign_id,
    )
    return stats


async def _advance_campaign_to_gate(
    session: AsyncSession,
    provider: LLMProvider,
    campaign_id: str,
    niche_rules_path: str,
    qualification_rules_path: str,
) -> dict[str, Any]:
    """Carries newly-drilled niches the rest of the frozen flow's
    distance: canonicalize -> verify -> estimate-ecosystem -> qualify ->
    select -> onboard -> research (through to Dossier / HUMAN_REVIEW).
    These are the same worker calls ``POST /campaigns/{id}/{stage}`` makes
    by hand; chaining them here is what makes a pass end-to-end
    unattended, so the only human touchpoint is the decision gate on the
    dossiers it produces, not clicking each stage in turn.

    A dependency chain, not an independent checklist: canonicalize's
    PROMOTED niches feed verify, verify's VERIFIED CampaignNiche rows feed
    estimate-ecosystem and qualify, qualify's score feeds select, select's
    SELECTED rows feed onboard, and onboard's Creator rows feed
    research-campaign. A stage that fails stops the chain there rather
    than running the next one against incomplete input — but everything
    that DID complete is already durable (each stage commits its own
    ResearchRun via flush; the caller commits the whole pass), so a later
    failure never loses earlier progress.
    """
    from corp.workers.acquisition.creator_onboarding import CreatorOnboarder
    from corp.workers.adapters.base import close_quietly
    from corp.workers.adapters.registry import build_search_adapter
    from corp.workers.campaign_config import batch_config, load_campaign, stage_configs
    from corp.workers.campaign_research import CampaignResearchBatch
    from corp.workers.intelligence.ecosystem_estimator import (
        EcosystemEstimator,
        YouTubeAPIEnricher,
    )
    from corp.workers.intelligence.embeddings import SentenceTransformerEmbedder
    from corp.workers.intelligence.niche_canonicalization import CanonConfig, NicheCanonicalizer
    from corp.workers.intelligence.niche_selection import NicheSelector
    from corp.workers.intelligence.niche_verification import NicheVerifier
    from corp.workers.orchestrator import ResearchOrchestrator

    pipeline: dict[str, Any] = {}

    async def stage(name: str, work: Awaitable[Any]) -> bool:
        try:
            run = await work
        except Exception:
            logger.exception(
                "Discovery pass: %s failed for campaign %s", name, campaign_id,
            )
            pipeline[name] = {
                "status": "failed",
                "error": f"{name} failed; details in the server log",
            }
            return False
        pipeline[name] = {"run_id": run.id, "status": run.status}
        # A stage can finish without raising and still report "failed"
        # (finish_run/fail_run's status is the signal, same convention as
        # ResearchOrchestrator.step) -- stop the chain there too, not just
        # on an exception.
        return bool(run.status != "failed")

    # The campaign's own knobs (target niche count, creator follower band,
    # creators per niche, human-gate capacity) configure every stage that
    # has one -- the same mapping POST /campaigns/{id}/{stage} uses, so a
    # pass on a campaign behaves as that campaign's row says, not as the
    # worker defaults say.
    campaign = await load_campaign(session, campaign_id)
    configs = stage_configs(campaign)

    recheck_days = DiscoveryConfig.from_rules(niche_rules_path).recheck_days
    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    canon = NicheCanonicalizer(embedder, session, CanonConfig(recheck_days=recheck_days))
    if not await stage("canonicalize", canon.canonicalize(campaign_id)):
        return pipeline

    if not await stage("verify", NicheVerifier(session).verify(campaign_id)):
        return pipeline

    youtube = build_search_adapter("youtube")
    enricher = YouTubeAPIEnricher(settings.youtube_api_key) if settings.youtube_api_key else None
    try:
        estimator = EcosystemEstimator(
            youtube, session, configs.ecosystem, enricher=enricher,
        )
        if not await stage("estimate_ecosystem", estimator.estimate(campaign_id)):
            return pipeline
    finally:
        await close_quietly(youtube)

    qualifier = NicheQualifier(session, qualification_rules_path)
    if not await stage("qualify", qualifier.qualify_campaign(campaign_id)):
        return pipeline

    selector = NicheSelector(session, configs.selection)
    if not await stage("select", selector.select(campaign_id)):
        return pipeline

    onboard_adapter = build_search_adapter("youtube")
    onboard_enricher = (
        YouTubeAPIEnricher(settings.youtube_api_key) if settings.youtube_api_key else None
    )
    try:
        onboarder = CreatorOnboarder(
            onboard_adapter, session, configs.onboarding, enricher=onboard_enricher,
        )
        if not await stage("onboard", onboarder.onboard(campaign_id)):
            return pipeline
    finally:
        await close_quietly(onboard_adapter)

    orchestrator = ResearchOrchestrator(session, provider, lambda: embedder)
    # Counted now, after onboard, so the limit reflects the gate as it
    # stands when research starts.
    batch = CampaignResearchBatch(orchestrator, session, await batch_config(session, campaign))
    await stage("research_campaign", batch.run_campaign(campaign_id))
    return pipeline


# Per tick: an LLM provider to drill with, None when none is configured
# (the pass cannot run at all), or DiscoveryDeferredError to skip.
ProviderFactory = Callable[[], Awaitable["DiscoveryHandle | None"]]


@dataclass
class DiscoveryHandle:
    """A provider plus how to release it once the tick is done."""

    provider: LLMProvider
    trend_provider: TrendProvider | None
    aclose: Callable[[], Awaitable[None]]


class DiscoveryScanScheduler:
    """In-process loop running one :func:`run_discovery_pass` per tick.

    Start it from application startup and stop it at shutdown, exactly
    like the registry re-scan scheduler. ``is_busy`` lets it stand down
    while the console is already running a campaign job, so an unattended
    pass never competes with a human-initiated one for the same quota.
    """

    MAX_CONSECUTIVE_FAILURES = 5

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider_factory: ProviderFactory,
        *,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        topics_per_pass: int | None = None,
        niche_rules_path: str = "rules/niche_discovery_prompt.yaml",
        qualification_rules_path: str = "rules/niche_qualification.yaml",
        broad_topics_path: str = DEFAULT_BROAD_TOPICS_PATH,
        is_busy: Callable[[], bool] | None = None,
    ) -> None:
        self._broad_topics_path = broad_topics_path
        self._session_factory = session_factory
        self._provider_factory = provider_factory
        self._interval_seconds = interval_seconds
        self._topics_per_pass = topics_per_pass
        self._niche_rules_path = niche_rules_path
        self._qualification_rules_path = qualification_rules_path
        self._is_busy = is_busy
        self._task: asyncio.Task[None] | None = None
        self._consecutive_failures = 0

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            # Expected, not an error: cancel() above is how stop() ends the
            # loop, and awaiting a cancelled task re-raises CancelledError.
            pass
        self._task = None

    async def _run_forever(self) -> None:
        while self._consecutive_failures < self.MAX_CONSECUTIVE_FAILURES:
            await self._tick()
            # Check again right after the tick that may have just pushed us
            # over the limit: falling through to the sleep below first
            # would leave the task alive (and start() a no-op, since it
            # only returns early when self._task is not None) for up to
            # interval_seconds * 32 -- 32 days at the default interval --
            # after already having logged that it gave up.
            if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                break
            delay = self._interval_seconds
            if self._consecutive_failures > 0:
                delay = min(
                    self._interval_seconds * (2 ** self._consecutive_failures),
                    self._interval_seconds * 32,
                )
            await asyncio.sleep(delay)

    async def _tick(self) -> None:
        try:
            if self._is_busy is not None and self._is_busy():
                logger.info("Discovery pass skipped: a campaign job is already running")
                self._consecutive_failures = 0
                return

            handle: DiscoveryHandle | None
            try:
                handle = await self._provider_factory()
            except DiscoveryDeferredError as why:
                logger.info("Discovery pass deferred: %s", why)
                self._consecutive_failures = 0
                return
            if handle is None:
                logger.info("Discovery pass skipped: no LLM provider configured")
                self._consecutive_failures = 0
                return

            try:
                async with self._session_factory() as session:
                    try:
                        await run_discovery_pass(
                            session,
                            handle.provider,
                            trend_provider=handle.trend_provider,
                            niche_rules_path=self._niche_rules_path,
                            qualification_rules_path=self._qualification_rules_path,
                            topics_per_pass=self._topics_per_pass,
                            broad_topics_path=self._broad_topics_path,
                        )
                        await session.commit()
                    except Exception:
                        await session.rollback()
                        raise
            finally:
                try:
                    await handle.aclose()
                except Exception:  # noqa: BLE001 — the pass is already committed
                    logger.exception("Discovery pass: releasing the provider failed")
            self._consecutive_failures = 0
        except Exception:  # noqa: BLE001 — a failed tick must not kill the loop
            self._consecutive_failures += 1
            logger.exception(
                "Discovery pass tick failed (consecutive=%d/%d)",
                self._consecutive_failures,
                self.MAX_CONSECUTIVE_FAILURES,
            )
            if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    "Discovery scheduler giving up after %d consecutive failures",
                    self._consecutive_failures,
                )
