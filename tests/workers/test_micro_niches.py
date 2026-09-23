"""Creator-first discovery, step 1: audience clusters → approval queue."""

import itertools
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from corp.core.models.creator import Creator, CreatorPlatformAccount
from corp.core.models.intelligence import ProblemCluster
from corp.core.models.micro_niche import MicroNicheStatus, MicroNicheSuggestion
from corp.core.models.niche import Niche
from corp.workers.intelligence.micro_niches import MicroNicheSeeder, normalize_label
from corp.workers.intelligence.niche_discovery import DiscoveryConfig

_handles = itertools.count()


def _rules(**exclusions: list[str]) -> DiscoveryConfig:
    return DiscoveryConfig(
        max_depth=3, breadth_depth_0=15, breadth_per_branch=10, recheck_days=90,
        max_evidence_texts=40, max_text_chars=300, exclusions=dict(exclusions),
    )


def _seeder(session, **kw) -> MicroNicheSeeder:
    kw.setdefault("discovery_config", _rules())
    return MicroNicheSeeder(session, **kw)


async def _creator(session, followers: int | None = 50_000, niche: str = "woodworking",
                   archived: bool = False) -> Creator:
    c = Creator(name=f"Creator {next(_handles)}", niche=niche)
    if archived:
        c.archived_at = datetime.now(UTC)
    session.add(c)
    await session.flush()
    if followers is not None:
        session.add(CreatorPlatformAccount(
            creator_id=c.id, platform="youtube", handle=f"@h{next(_handles)}",
            subscriber_count=followers,
        ))
        await session.flush()
    return c


async def _cluster(session, creator: Creator, label: str, frequency: int = 5,
                   superseded: bool = False) -> ProblemCluster:
    cl = ProblemCluster(creator_id=creator.id, label=label, frequency=frequency)
    if superseded:
        cl.superseded_at = datetime.now(UTC)
    session.add(cl)
    await session.flush()
    return cl


async def _queue(session) -> list[MicroNicheSuggestion]:
    return list((await session.execute(select(MicroNicheSuggestion))).scalars().all())


# ── The basic bridge ─────────────────────────────────────────────────


async def test_an_audience_cluster_becomes_a_pending_suggestion(clean_db):
    c = await _creator(clean_db, followers=50_000, niche="woodworking")
    cl = await _cluster(clean_db, c, "Finishing outdoor oak furniture", frequency=7)

    stats = await _seeder(clean_db).suggest()

    assert stats.created == 1
    [s] = await _queue(clean_db)
    assert s.status == MicroNicheStatus.PENDING
    assert s.label == "Finishing outdoor oak furniture"
    assert s.normalized_label == "finishing outdoor oak furniture"
    assert s.problem_cluster_id == cl.id
    assert s.creator_id == c.id
    assert s.creator_niche == "woodworking"
    assert s.follower_count == 50_000
    assert s.total_frequency == 7
    assert s.source_creator_count == 1


async def test_suggesting_drills_nothing_and_needs_no_provider(clean_db):
    """Approval-first: generating the queue must not touch the drill engine."""
    c = await _creator(clean_db)
    await _cluster(clean_db, c, "Shop dust collection on a budget")
    # No LLM provider, no adapters: suggest() takes only a session.
    await _seeder(clean_db).suggest()
    from corp.core.models.workflow import ResearchRun

    runs = (await clean_db.execute(select(ResearchRun))).scalars().all()
    assert runs == []


# ── Filters ──────────────────────────────────────────────────────────


async def test_low_frequency_clusters_are_anecdotes_not_niches(clean_db):
    c = await _creator(clean_db)
    await _cluster(clean_db, c, "One person's complaint", frequency=2)
    stats = await _seeder(clean_db, min_frequency=3).suggest()
    assert stats.skipped_low_frequency == 1
    assert await _queue(clean_db) == []


@pytest.mark.parametrize("followers", [9_999, 200_001, 5_000_000])
async def test_creators_outside_the_band_are_skipped(clean_db, followers):
    c = await _creator(clean_db, followers=followers)
    await _cluster(clean_db, c, "Some real problem")
    stats = await _seeder(clean_db).suggest()
    assert stats.skipped_out_of_band == 1
    assert await _queue(clean_db) == []


@pytest.mark.parametrize("followers", [10_000, 200_000])
async def test_band_edges_are_inclusive(clean_db, followers):
    c = await _creator(clean_db, followers=followers)
    await _cluster(clean_db, c, "Edge of the band problem")
    assert (await _seeder(clean_db).suggest()).created == 1


async def test_unknown_follower_count_is_let_through_and_flagged(clean_db):
    c = await _creator(clean_db, followers=None)
    await _cluster(clean_db, c, "Hand-added creator problem")
    await _seeder(clean_db).suggest()
    [s] = await _queue(clean_db)
    assert s.follower_count is None


async def test_the_largest_account_decides_the_band(clean_db):
    c = await _creator(clean_db, followers=20_000)
    clean_db.add(CreatorPlatformAccount(
        creator_id=c.id, platform="tiktok", handle="@big", subscriber_count=900_000,
    ))
    await clean_db.flush()
    await _cluster(clean_db, c, "Cross-platform problem")
    assert (await _seeder(clean_db).suggest()).skipped_out_of_band == 1


async def test_archived_creators_are_ignored(clean_db):
    c = await _creator(clean_db, archived=True)
    await _cluster(clean_db, c, "Archived creator problem")
    stats = await _seeder(clean_db).suggest()
    assert stats.clusters_seen == 0


async def test_superseded_clusters_are_ignored(clean_db):
    c = await _creator(clean_db)
    await _cluster(clean_db, c, "Old clustering run", superseded=True)
    assert (await _seeder(clean_db).suggest()).clusters_seen == 0


async def test_excluded_niches_are_never_surfaced(clean_db):
    c = await _creator(clean_db)
    await _cluster(clean_db, c, "Online gambling bankroll tips")
    stats = await _seeder(
        clean_db, discovery_config=_rules(adult_gambling_vice=["gambling"])
    ).suggest()
    assert stats.skipped_excluded == 1
    assert await _queue(clean_db) == []


async def test_labels_inside_their_research_window_are_skipped(clean_db):
    c = await _creator(clean_db)
    await _cluster(clean_db, c, "Sharpening chisels")
    clean_db.add(Niche(
        canonical_name="sharpening chisels",
        last_researched_at=datetime.now(UTC),
        next_recheck_at=datetime.now(UTC) + timedelta(days=90),
    ))
    await clean_db.flush()
    stats = await _seeder(clean_db).suggest()
    assert stats.skipped_registry_fresh == 1
    assert await _queue(clean_db) == []


async def test_suggest_can_be_scoped_to_one_creator(clean_db):
    a = await _creator(clean_db)
    b = await _creator(clean_db)
    await _cluster(clean_db, a, "Problem A")
    await _cluster(clean_db, b, "Problem B")
    await _seeder(clean_db).suggest(creator_id=a.id)
    assert [s.label for s in await _queue(clean_db)] == ["Problem A"]


# ── Aggregation across creators ──────────────────────────────────────


async def test_the_same_problem_in_several_audiences_is_one_suggestion(clean_db):
    a = await _creator(clean_db, followers=30_000)
    b = await _creator(clean_db, followers=80_000)
    await _cluster(clean_db, a, "Finishing Outdoor Oak", frequency=4)
    await _cluster(clean_db, b, "finishing  outdoor oak", frequency=9)

    stats = await _seeder(clean_db).suggest()

    assert stats.created == 1
    [s] = await _queue(clean_db)
    assert s.source_creator_count == 2
    assert s.total_frequency == 13
    assert s.creator_id == b.id, "points at the strongest source"
    assert s.follower_count == 80_000
    assert [src["frequency"] for src in s.sources] == [9, 4]


async def test_rerunning_is_idempotent(clean_db):
    c = await _creator(clean_db)
    await _cluster(clean_db, c, "Garage shop layout", frequency=6)
    await _seeder(clean_db).suggest()
    stats = await _seeder(clean_db).suggest()
    assert stats.created == 0 and stats.updated == 1
    [s] = await _queue(clean_db)
    assert s.total_frequency == 6
    assert s.source_creator_count == 1


async def test_re_researching_a_creator_refreshes_not_double_counts(clean_db):
    """Re-research supersedes a creator's clusters and makes new ones. The
    creator must stay one source, with the new frequency."""
    c = await _creator(clean_db)
    old = await _cluster(clean_db, c, "Garage shop layout", frequency=4)
    await _seeder(clean_db).suggest()

    old.superseded_at = datetime.now(UTC)
    new = await _cluster(clean_db, c, "Garage shop layout", frequency=11)
    await _seeder(clean_db).suggest()

    [s] = await _queue(clean_db)
    assert s.source_creator_count == 1
    assert s.total_frequency == 11
    assert s.problem_cluster_id == new.id


async def test_a_new_creator_adds_a_source_to_a_pending_suggestion(clean_db):
    a = await _creator(clean_db)
    await _cluster(clean_db, a, "Router table jigs", frequency=5)
    await _seeder(clean_db).suggest()

    b = await _creator(clean_db)
    await _cluster(clean_db, b, "Router table jigs", frequency=3)
    await _seeder(clean_db).suggest(creator_id=b.id)

    [s] = await _queue(clean_db)
    assert s.source_creator_count == 2
    assert s.total_frequency == 8


# ── Decisions stick ──────────────────────────────────────────────────


@pytest.mark.parametrize("decided", [MicroNicheStatus.REJECTED, MicroNicheStatus.APPROVED])
async def test_decided_suggestions_are_never_requeued_or_changed(clean_db, decided):
    c = await _creator(clean_db)
    await _cluster(clean_db, c, "Epoxy river tables", frequency=5)
    await _seeder(clean_db).suggest()
    [s] = await _queue(clean_db)
    s.status = decided
    await clean_db.flush()

    b = await _creator(clean_db)
    await _cluster(clean_db, b, "Epoxy river tables", frequency=50)
    stats = await _seeder(clean_db).suggest()

    assert stats.skipped_already_decided == 1
    assert stats.created == 0
    [s] = await _queue(clean_db)
    assert s.status == decided
    assert s.total_frequency == 5, "a decided row is history; it is not rewritten"


def test_normalize_label():
    assert normalize_label("  Finishing   Outdoor\tOak ") == "finishing outdoor oak"
