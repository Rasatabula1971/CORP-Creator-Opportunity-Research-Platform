"""Unit tests for the Level 0 trend scan (CORP1 Step 1)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from corp.workers.intelligence.niche_discovery import DiscoveryConfig
from corp.workers.intelligence.trend_scan import (
    SeedTopic,
    TrendScanConfig,
    TrendScanner,
    TrendSignalUnavailableError,
    _score_from_items,
)


@dataclass
class _Item:
    """Stands in for NormalizedContent — only .metadata is read."""

    metadata: dict[str, Any]


class _FakeTrends:
    """A TrendProvider that returns canned momentum, or raises."""

    def __init__(
        self, scores: dict[str, float] | None = None, fail: set[str] | None = None
    ) -> None:
        self.scores = scores or {}
        self.fail = fail or set()
        self.calls: list[str] = []

    async def fetch_trend(self, query: str) -> list[_Item]:
        self.calls.append(query)
        if query in self.fail:
            raise RuntimeError(f"trends is down for {query}")
        if query not in self.scores:
            return []
        return [_Item(metadata={"avg_interest": self.scores[query]})]


def _config(*topics: str, per_pass: int = 3, fallback: bool = True) -> TrendScanConfig:
    return TrendScanConfig(
        topics=tuple(topics),
        topics_per_pass=per_pass,
        geo="US",
        allow_rotation_fallback=fallback,
    )


def _discovery(**exclusions: list[str]) -> DiscoveryConfig:
    return DiscoveryConfig(
        max_depth=3,
        breadth_depth_0=15,
        breadth_per_branch=10,
        recheck_days=90,
        max_evidence_texts=40,
        max_text_chars=300,
        exclusions=dict(exclusions),
    )


# ── Momentum extraction ──────────────────────────────────────────────


def test_score_prefers_avg_interest_and_clamps():
    assert _score_from_items([_Item({"avg_interest": 73.4})]) == 73.4
    assert _score_from_items([_Item({"avg_interest": 500})]) == 100.0
    assert _score_from_items([_Item({"avg_interest": -5})]) == 0.0


def test_score_takes_the_best_of_several_series():
    items = [_Item({"avg_interest": 10}), _Item({"avg_interest": 60})]
    assert _score_from_items(items) == 60.0


def test_score_ignores_unparseable_interest():
    assert _score_from_items([_Item({"avg_interest": "not a number"})]) == 1.0


def test_score_without_a_series_is_a_weak_count_signal():
    """No pytrends: the adapter returns keyword-matched trending items with
    no interest series. Those must rank below any measured topic."""
    assert _score_from_items([_Item({}), _Item({})]) == 2.0
    assert _score_from_items([_Item({})] * 50) == 10.0  # capped
    assert _score_from_items([]) is None


# ── Ranking ──────────────────────────────────────────────────────────


async def test_scan_ranks_by_momentum_descending(clean_db):
    scanner = TrendScanner(
        clean_db,
        trend_provider=_FakeTrends({"baking": 20.0, "woodworking": 90.0, "yoga": 55.0}),
        config=_config("baking", "woodworking", "yoga"),
        discovery_config=_discovery(),
    )
    seeds, stats = await scanner.scan()
    assert [s.topic for s in seeds] == ["woodworking", "yoga", "baking"]
    assert all(s.reason == "trends_momentum" for s in seeds)
    assert stats.scored == 3
    assert stats.selected == 3


async def test_scan_respects_topics_per_pass(clean_db):
    scanner = TrendScanner(
        clean_db,
        trend_provider=_FakeTrends({"a": 10.0, "b": 20.0, "c": 30.0}),
        config=_config("a", "b", "c", per_pass=2),
        discovery_config=_discovery(),
    )
    seeds, _ = await scanner.scan()
    assert [s.topic for s in seeds] == ["c", "b"]


async def test_measured_topics_outrank_unmeasured_ones(clean_db):
    """A topic Trends could not score must not jump a topic it did."""
    scanner = TrendScanner(
        clean_db,
        trend_provider=_FakeTrends({"baking": 1.0}),
        config=_config("baking", "unmeasured"),
        discovery_config=_discovery(),
    )
    seeds, _ = await scanner.scan()
    assert [s.topic for s in seeds] == ["baking", "unmeasured"]
    assert seeds[0].reason == "trends_momentum"
    assert seeds[1].reason == "rotation"


# ── Degrading ────────────────────────────────────────────────────────


async def test_scan_still_returns_topics_with_no_trend_provider(clean_db):
    """The crawler must keep crawling when the ranking signal is absent."""
    scanner = TrendScanner(
        clean_db,
        trend_provider=None,
        config=_config("baking", "woodworking"),
        discovery_config=_discovery(),
    )
    seeds, stats = await scanner.scan()
    assert {s.topic for s in seeds} == {"baking", "woodworking"}
    assert all(s.reason == "rotation" for s in seeds)
    assert all(s.momentum is None for s in seeds)
    assert stats.scored == 0


async def test_a_failing_lookup_does_not_sink_the_scan(clean_db):
    trends = _FakeTrends({"woodworking": 40.0}, fail={"baking"})
    scanner = TrendScanner(
        clean_db,
        trend_provider=trends,
        config=_config("baking", "woodworking"),
        discovery_config=_discovery(),
    )
    seeds, stats = await scanner.scan()
    assert [s.topic for s in seeds] == ["woodworking", "baking"]
    assert stats.momentum_failures == 1


async def test_rotation_fallback_can_be_refused(clean_db):
    scanner = TrendScanner(
        clean_db,
        trend_provider=_FakeTrends(fail={"baking"}),
        config=_config("baking", fallback=False),
        discovery_config=_discovery(),
    )
    with pytest.raises(TrendSignalUnavailableError):
        await scanner.scan()


# ── Deterministic filters ────────────────────────────────────────────


async def test_stage3_exclusions_drop_topics_before_any_llm_spend(clean_db):
    scanner = TrendScanner(
        clean_db,
        trend_provider=_FakeTrends({"baking": 10.0}),
        config=_config("baking", "online gambling tips"),
        discovery_config=_discovery(adult_gambling_vice=["gambling"]),
    )
    seeds, stats = await scanner.scan()
    assert [s.topic for s in seeds] == ["baking"]
    assert stats.excluded == 1


async def test_registry_fresh_topics_are_skipped(clean_db):
    """A niche inside its 90-day window must not be re-drilled."""
    from corp.core.models.niche import Niche

    clean_db.add(
        Niche(
            canonical_name="baking",
            last_researched_at=datetime.now(UTC),
            next_recheck_at=datetime.now(UTC) + timedelta(days=90),
        )
    )
    await clean_db.flush()

    scanner = TrendScanner(
        clean_db,
        trend_provider=None,
        config=_config("baking", "woodworking"),
        discovery_config=_discovery(),
    )
    seeds, stats = await scanner.scan()
    assert [s.topic for s in seeds] == ["woodworking"]
    assert stats.registry_fresh == 1


async def test_a_topic_past_its_recheck_window_is_due_again(clean_db):
    from corp.core.models.niche import Niche

    clean_db.add(
        Niche(
            canonical_name="baking",
            last_researched_at=datetime.now(UTC) - timedelta(days=120),
            next_recheck_at=datetime.now(UTC) - timedelta(days=30),
        )
    )
    await clean_db.flush()

    scanner = TrendScanner(
        clean_db,
        trend_provider=None,
        config=_config("baking"),
        discovery_config=_discovery(),
    )
    seeds, stats = await scanner.scan()
    assert [s.topic for s in seeds] == ["baking"]
    assert stats.registry_fresh == 0


async def _seed_topic_drill(
    session, topic: str, *, days_ago: float, status: str = "completed",
) -> None:
    """A discover() call's own ResearchRun history for ``topic`` -- what
    the real pipeline leaves behind, unlike a Niche row named after the
    raw catalogue keyword (the drill engine always synthesizes more
    specific niche names from it, so that literal string never becomes
    one)."""
    from corp.core.models.workflow import ResearchRun

    when = datetime.now(UTC) - timedelta(days=days_ago)
    session.add(
        ResearchRun(
            config_snapshot={"pipeline": "niche_discovery_recursive", "topic": topic},
            status=status,
            completed_at=when,
        )
    )
    await session.flush()


async def test_rotation_puts_the_least_recently_drilled_first(clean_db):
    # Both due, but drilled at different times.
    await _seed_topic_drill(clean_db, "baking", days_ago=100)
    await _seed_topic_drill(clean_db, "woodworking", days_ago=300)

    scanner = TrendScanner(
        clean_db,
        trend_provider=None,
        config=_config("baking", "woodworking"),
        discovery_config=_discovery(),
    )
    seeds, _ = await scanner.scan()
    # Never-drilled would come first; of these two, the older one wins.
    assert [s.topic for s in seeds] == ["woodworking", "baking"]


async def test_never_drilled_outranks_previously_drilled(clean_db):
    await _seed_topic_drill(clean_db, "baking", days_ago=100)

    scanner = TrendScanner(
        clean_db,
        trend_provider=None,
        config=_config("baking", "brand new topic"),
        discovery_config=_discovery(),
    )
    seeds, _ = await scanner.scan()
    assert seeds[0].topic == "brand new topic"


async def test_a_recently_drilled_topic_is_not_reselected(clean_db):
    """The actual production shape this whole mechanism exists for: the
    broad catalogue keyword itself never becomes a Niche row (the LLM
    always synthesizes more specific names from it), so freshness must
    come from the drill's own ResearchRun history, not the Niche table."""
    await _seed_topic_drill(clean_db, "baking", days_ago=5)

    scanner = TrendScanner(
        clean_db,
        trend_provider=None,
        config=_config("baking", "woodworking"),
        discovery_config=_discovery(),
    )
    seeds, stats = await scanner.scan()
    assert [s.topic for s in seeds] == ["woodworking"]
    assert stats.registry_fresh == 1


async def test_a_failed_drill_does_not_block_a_quick_retry(clean_db):
    """A topic where every evidence source errored produced nothing --
    unlike a real (however thin) result, it shouldn't cost the topic the
    full 90-day window."""
    await _seed_topic_drill(clean_db, "baking", days_ago=1, status="failed")

    scanner = TrendScanner(
        clean_db, trend_provider=None, config=_config("baking"), discovery_config=_discovery(),
    )
    seeds, stats = await scanner.scan()
    assert [s.topic for s in seeds] == ["baking"]
    assert stats.registry_fresh == 0


async def test_a_topic_drilled_past_its_recheck_window_is_due_again(clean_db):
    await _seed_topic_drill(clean_db, "baking", days_ago=120)

    scanner = TrendScanner(
        clean_db, trend_provider=None, config=_config("baking"), discovery_config=_discovery(),
    )
    seeds, stats = await scanner.scan()
    assert [s.topic for s in seeds] == ["baking"]
    assert stats.registry_fresh == 0


async def test_empty_catalogue_yields_nothing(clean_db):
    scanner = TrendScanner(
        clean_db, trend_provider=None, config=_config(), discovery_config=_discovery()
    )
    seeds, stats = await scanner.scan()
    assert seeds == []
    assert stats.catalogue == 0


async def test_zero_limit_spends_no_momentum_calls(clean_db):
    trends = _FakeTrends({"baking": 10.0})
    scanner = TrendScanner(
        clean_db,
        trend_provider=trends,
        config=_config("baking"),
        discovery_config=_discovery(),
    )
    seeds, _ = await scanner.scan(limit=0)
    assert seeds == []
    assert trends.calls == []


# ── The shipped catalogue ────────────────────────────────────────────


def test_shipped_catalogue_loads_and_is_normalised():
    cfg = TrendScanConfig.from_rules("rules/broad_topics.yaml")
    assert cfg.topics, "the catalogue must not be empty"
    assert len(set(cfg.topics)) == len(cfg.topics), "duplicate topics"
    assert all(t == t.strip().lower() for t in cfg.topics)
    assert cfg.topics_per_pass >= 1


def test_shipped_catalogue_survives_the_frozen_exclusion_rules():
    """A catalogue entry that trips a Stage 3 exclusion would be dead
    weight — dropped on every pass, forever."""
    from corp.workers.intelligence.niche_discovery import matched_exclusion

    cfg = TrendScanConfig.from_rules("rules/broad_topics.yaml")
    rules = DiscoveryConfig.from_rules("rules/niche_discovery_prompt.yaml")
    offenders = {
        t: matched_exclusion(t, rules.exclusions)
        for t in cfg.topics
        if matched_exclusion(t, rules.exclusions)
    }
    assert not offenders, f"catalogue topics permanently excluded: {offenders}"


def test_seed_topic_is_hashable_and_frozen():
    seed = SeedTopic(topic="baking", momentum=1.0, reason="rotation")
    with pytest.raises(AttributeError):
        seed.topic = "other"  # type: ignore[misc]


async def test_an_outage_warns_once_not_once_per_topic(clean_db, caplog):
    import logging

    topics = ("baking", "woodworking", "yoga", "fishing")
    scanner = TrendScanner(
        clean_db,
        trend_provider=_FakeTrends(fail=set(topics)),
        config=_config(*topics, per_pass=4),
        discovery_config=_discovery(),
    )
    with caplog.at_level(logging.WARNING, logger="corp.workers.intelligence.trend_scan"):
        seeds, stats = await scanner.scan()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert stats.momentum_failures == 4
    assert len(warnings) == 2, [r.getMessage() for r in warnings]  # first failure + summary
    assert "4 of 4" in warnings[-1].getMessage()
    assert len(seeds) == 4, "the pass must still select topics"
