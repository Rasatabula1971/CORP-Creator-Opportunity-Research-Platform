"""The autonomous discovery crawler — CORP1 Step 1 with no user input.

One pass is: Level 0 trend scan → recursive niche drill-down per seed
topic → qualification of everything the campaign now holds. That is the
front of the spec's pipeline running on a timer instead of on a request.

**Where a pass stops.** After qualification. It deliberately does not go
on to select/onboard/research: those spend YouTube quota and a research
run per creator, and the point of an unattended crawler is that you see
what it found before it spends that. The qualified niches sit on the
campaign dashboard; taking one further is a normal campaign-stage call.

**Off by default.** ``settings.discovery_enabled`` gates the scheduler, so
installing this does not silently start burning LLM quota. The manual
trigger (``POST /discovery/run``) works either way, which is the intended
way to watch one pass end to end before switching the timer on.

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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from corp.config import Settings
from corp.core.models.campaign import Campaign, CampaignStatus
from corp.workers.intelligence.niche_discovery import RecursiveNicheDiscovery
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "topics_selected": self.topics_selected,
            "topics_drilled": self.topics_drilled,
            "topics_failed": self.topics_failed,
            "qualified": self.qualified,
            "campaign_id": self.campaign_id,
            "scan": self.scan,
            "topics": self.topics,
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

    Matched case-insensitively on name so a renamed-then-restored campaign,
    or one created by a different code path, is reused rather than
    duplicated.
    """
    result = await session.execute(
        select(Campaign).where(func.lower(Campaign.name) == name.lower()).limit(1)
    )
    campaign = result.scalar_one_or_none()
    if campaign is not None:
        return campaign
    campaign = Campaign(
        name=name,
        status=CampaignStatus.ACTIVE,
        started_at=datetime.now(UTC),
    )
    session.add(campaign)
    await session.flush()
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
        except Exception as exc:  # noqa: BLE001 — one topic must not sink the pass
            stats.topics_failed += 1
            stats.topics.append(
                {
                    "topic": seed.topic,
                    "reason": seed.reason,
                    "momentum": seed.momentum,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            logger.exception("Discovery pass: drilling %r failed", seed.topic)
            continue
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

    # Qualify once for the campaign rather than per topic: qualification
    # ranks the campaign's niches against each other, so running it after
    # every drill would score early topics against a half-built field.
    if stats.topics_drilled:
        try:
            await NicheQualifier(session, qualification_rules_path).qualify_campaign(campaign_id)
            stats.qualified = True
        except Exception:  # noqa: BLE001 — the drilled niches are already durable
            logger.exception("Discovery pass: qualification failed; niches are still saved")

    logger.info(
        "Discovery pass: selected=%d drilled=%d failed=%d qualified=%s campaign=%s",
        stats.topics_selected,
        stats.topics_drilled,
        stats.topics_failed,
        stats.qualified,
        campaign_id,
    )
    return stats


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
