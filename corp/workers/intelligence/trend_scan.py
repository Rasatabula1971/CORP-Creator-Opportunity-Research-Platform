"""CORP1 Step 1, Level 0 — the autonomous trend scan.

The drill engine (:mod:`corp.workers.intelligence.niche_discovery`) can
recurse a broad topic down to a leaf niche, but something has to hand it
that broad topic. Until this module existed, only a human could: the
campaign ``discover`` stage refused to run without a ``query``. This is
the piece that lets a pass start with no user input at all, which the
spec freezes as an automated action ("Topic scan (Google Trends pull) —
AUTO").

**Where topics come from.** A curated catalogue (``rules/broad_topics.yaml``)
bounds the universe; a momentum source ranks it — YouTube's official
trending charts by default (:mod:`corp.workers.adapters.youtube_trends`),
Google Trends optionally. That split is deliberate. A trending feed —
Google's or YouTube's — reports what spiked in the last 24 hours
— news, sport, celebrities — while Level 0 wants durable areas a digital
product can be built for ("small business", "home organization", the
spec's own examples). Drilling a news spike costs a full recursive LLM
pass and yields a niche tree nobody can build for. So the momentum source decides
*which catalogue topics have momentum now and therefore go first*; it
does not get to nominate "Lakers score" as a research target.

**Degrading.** Momentum is a ranking signal, never a gate. The YouTube
source needs an API key and draws on a daily quota; the Google Trends one
needs pytrends and an undocumented, rate-limited endpoint; either lookup
can simply fail. When it does, the scanner falls back
to least-recently-researched ordering, which rotates through the catalogue
on its own. A crawler that stops crawling because a ranking signal went
missing would be worse than one that keeps going in a fixed order.

**What it will not return.** Two deterministic filters, both reusing the
engines that already own those rules rather than reimplementing them:

* Stage 3 exclusions (:func:`~corp.workers.intelligence.niche_discovery.matched_exclusion`)
  — never an LLM judgment call.
* The research registry (:func:`~corp.workers.intelligence.niche_discovery.registry_fresh`)
  — a topic whose niche is inside its 90-day window is skipped, so a pass
  does not repeat work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.workflow import ResearchRun
from corp.core.scoring.niche_qualification import load_rules
from corp.workers.intelligence.niche_discovery import (
    PIPELINE as NICHE_DISCOVERY_PIPELINE,
)
from corp.workers.intelligence.niche_discovery import (
    DiscoveryConfig,
    matched_exclusion,
    registry_fresh,
)
from corp.workers.providers.capabilities import TrendProvider

logger = logging.getLogger(__name__)

DEFAULT_BROAD_TOPICS_PATH = "rules/broad_topics.yaml"


@dataclass(frozen=True, slots=True)
class TrendScanConfig:
    """The ``scan:`` block of rules/broad_topics.yaml, plus its topics."""

    topics: tuple[str, ...]
    topics_per_pass: int
    geo: str
    allow_rotation_fallback: bool

    @classmethod
    def from_rules(cls, rules_path: str = DEFAULT_BROAD_TOPICS_PATH) -> TrendScanConfig:
        rules = load_rules(rules_path)
        scan = rules.get("scan", {}) or {}
        raw_topics = rules.get("topics", []) or []
        # Normalise here so the catalogue can be edited loosely (stray case,
        # padding, a duplicate) without the scanner drilling the same topic
        # twice under two spellings. dict.fromkeys keeps first-seen order.
        cleaned = [str(t).strip() for t in raw_topics if str(t).strip()]
        deduped = tuple(dict.fromkeys(t.lower() for t in cleaned))
        return cls(
            topics=deduped,
            topics_per_pass=int(scan.get("topics_per_pass", 3)),
            geo=str(scan.get("geo", "US")),
            allow_rotation_fallback=bool(scan.get("allow_rotation_fallback", True)),
        )


@dataclass(frozen=True, slots=True)
class SeedTopic:
    """A broad topic cleared to enter recursive discovery."""

    topic: str
    # 0..100 from the momentum source's ``avg_interest``, or None when
    # no live signal was obtained for this topic.
    momentum: float | None
    # "trends_momentum" when the momentum source ranked it, "rotation" when it is here
    # because it is the least recently researched.
    reason: str


@dataclass
class TrendScanStats:
    """Why a pass returned what it did — surfaced in the run record so a
    scan that finds nothing is diagnosable without re-running it."""

    catalogue: int = 0
    excluded: int = 0
    registry_fresh: int = 0
    scored: int = 0
    momentum_failures: int = 0
    selected: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "catalogue": self.catalogue,
            "excluded": self.excluded,
            "registry_fresh": self.registry_fresh,
            "scored": self.scored,
            "momentum_failures": self.momentum_failures,
            "selected": self.selected,
        }


class TrendScanner:
    """Turns the broad-topic catalogue into a ranked list of seed topics.

    ``trend_provider`` is optional: without one (or when every lookup
    fails) the scan still returns topics, ordered by how long ago they
    were last researched.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        trend_provider: TrendProvider | None = None,
        config: TrendScanConfig | None = None,
        discovery_config: DiscoveryConfig | None = None,
        niche_rules_path: str = "rules/niche_discovery_prompt.yaml",
    ) -> None:
        self._session = session
        self._provider = trend_provider
        self._config = config or TrendScanConfig.from_rules()
        # The Stage 3 exclusion list lives in the drill engine's rules file;
        # read it from there so there is one frozen copy, not two.
        self._discovery = discovery_config or DiscoveryConfig.from_rules(niche_rules_path)

    @property
    def config(self) -> TrendScanConfig:
        return self._config

    async def scan(self, limit: int | None = None) -> tuple[list[SeedTopic], TrendScanStats]:
        """Return up to ``limit`` topics ready to drill, best first."""
        limit = self._config.topics_per_pass if limit is None else limit
        stats = TrendScanStats(catalogue=len(self._config.topics))

        non_excluded: list[str] = []
        for topic in self._config.topics:
            category = matched_exclusion(topic, self._discovery.exclusions)
            if category is not None:
                stats.excluded += 1
                logger.debug("Trend scan: %r excluded (%s)", topic, category)
                continue
            non_excluded.append(topic)

        # When this drilled last, read from ResearchRun history -- not the
        # Niche table. A catalogue keyword like "small business" never
        # appears there verbatim: the drill engine always synthesizes more
        # specific niche names from it (see niche_discovery.py's
        # synthesize_niches). Checking Niche.canonical_name here would
        # therefore never match, silently defeating both the freshness
        # skip below and the rotation fallback further down, so the same
        # handful of catalogue topics would be re-selected and re-drilled
        # every single pass, forever.
        last_drilled = await self._topic_scan_history(non_excluded)
        now = datetime.now(UTC).timestamp()
        recheck_seconds = self._discovery.recheck_days * 86400

        eligible: list[str] = []
        for topic in non_excluded:
            if await registry_fresh(self._session, topic):
                stats.registry_fresh += 1
                continue
            seen = last_drilled.get(topic)
            if seen is not None and (now - seen) < recheck_seconds:
                stats.registry_fresh += 1
                continue
            eligible.append(topic)

        if not eligible:
            logger.info(
                "Trend scan: nothing due (catalogue=%d excluded=%d fresh=%d)",
                stats.catalogue,
                stats.excluded,
                stats.registry_fresh,
            )
            return [], stats

        if limit <= 0:
            return [], stats

        momentum = await self._momentum_for(eligible, stats)

        def sort_key(topic: str) -> tuple[int, float, float, str]:
            score = momentum.get(topic)
            if score is not None:
                # Rank 0: a live signal. Negative score sorts desc.
                return (0, -score, 0.0, topic)
            # Rank 1: rotation. Never drilled (None) goes first, then
            # oldest first. Timestamps are compared as epoch seconds so a
            # missing value can share the tuple slot.
            seen = last_drilled.get(topic)
            return (1, 0.0, seen if seen is not None else float("-inf"), topic)

        ranked = sorted(eligible, key=sort_key)[:limit]
        selected = [
            SeedTopic(
                topic=t,
                momentum=momentum.get(t),
                reason="trends_momentum" if momentum.get(t) is not None else "rotation",
            )
            for t in ranked
        ]
        stats.selected = len(selected)
        logger.info(
            "Trend scan selected %d topic(s): %s",
            len(selected),
            ", ".join(f"{s.topic}({s.reason})" for s in selected),
        )
        return selected, stats

    # ── Momentum ─────────────────────────────────────────────────────

    async def _momentum_for(
        self, topics: list[str], stats: TrendScanStats
    ) -> dict[str, float]:
        """Best-effort momentum score per topic. Missing keys mean no
        signal, which the caller ranks by rotation instead."""
        if self._provider is None:
            logger.info("Trend scan: no trend provider; ranking by rotation")
            return {}

        scores: dict[str, float] = {}
        first_failure: str | None = None
        for topic in topics:
            try:
                items = await self._provider.fetch_trend(topic)
            except Exception as exc:  # noqa: BLE001 — a ranking signal, not the work
                stats.momentum_failures += 1
                # One outage fails every topic the same way; warn once and
                # summarise, rather than one warning per catalogue entry.
                if first_failure is None:
                    first_failure = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "Trend scan: momentum lookup failed for %r: %s", topic, first_failure
                    )
                else:
                    logger.debug("Trend scan: momentum lookup failed for %r: %s", topic, exc)
                continue
            score = _score_from_items(items)
            if score is None:
                continue
            scores[topic] = score
            stats.scored += 1

        if stats.momentum_failures > 1:
            logger.warning(
                "Trend scan: momentum unavailable for %d of %d topic(s); those are "
                "ranked by rotation (first error: %s)",
                stats.momentum_failures,
                len(topics),
                first_failure,
            )

        if not scores and not self._config.allow_rotation_fallback:
            # The operator asked for a live signal or nothing. Surface the
            # reason rather than silently drilling an arbitrary topic.
            raise TrendSignalUnavailableError(
                f"no momentum signal for any of {len(topics)} eligible topic(s) "
                f"and allow_rotation_fallback is false"
            )
        return scores

    async def _topic_scan_history(self, topics: list[str]) -> dict[str, float]:
        """Epoch seconds of each broad topic's last non-failed drill,
        read from the niche-discovery ResearchRun history (every
        discover() call records its ``topic`` in ``config_snapshot``).
        A "failed" run (every source errored, nothing produced) does not
        count, so a transient outage doesn't lock a topic out for the
        full recheck window; "partial" and "completed" both do."""
        if not topics:
            return {}
        lowered = [t.lower() for t in topics]
        topic_col = func.lower(ResearchRun.config_snapshot["topic"].astext)
        result = await self._session.execute(
            select(
                topic_col,
                func.max(func.coalesce(ResearchRun.completed_at, ResearchRun.created_at)),
            )
            .where(
                ResearchRun.config_snapshot["pipeline"].astext == NICHE_DISCOVERY_PIPELINE,
                topic_col.in_(lowered),
                ResearchRun.status != "failed",
            )
            .group_by(topic_col)
        )
        return {topic: seen.timestamp() for topic, seen in result.all() if seen is not None}


class TrendSignalUnavailableError(RuntimeError):
    """No live momentum signal, and the catalogue forbids rotation fallback."""


def _score_from_items(items: list[Any]) -> float | None:
    """Pull a 0..100 momentum score out of whatever the adapter returned.

    The YouTube trends adapter, and the Google Trends adapter with pytrends
    installed, each emit one ``interest`` item carrying
    ``metadata["avg_interest"]``. Google Trends without pytrends falls back
    to keyword-matched trending items, which carry no series — there the
    count of matching items is the only signal available, so treat it as a
    weak one rather than discarding the topic outright.
    """
    if not items:
        return None
    best: float | None = None
    for item in items:
        meta = getattr(item, "metadata", None) or {}
        raw = meta.get("avg_interest")
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        best = value if best is None else max(best, value)
    if best is not None:
        return max(0.0, min(100.0, best))
    # No interest series: fall back to "it showed up in the trending feed
    # at all", capped well below a real score so any measured topic wins.
    return min(10.0, float(len(items)))
