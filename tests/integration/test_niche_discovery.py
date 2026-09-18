"""Integration tests for RecursiveNicheDiscovery (CORP1 Stage 5, T3) against
real Postgres. All adapter network calls are faked via a monkeypatched
build_adapter -- these tests never touch the network."""

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.evidence import AccessMethod, ComplianceStatus, Evidence, EvidenceType
from corp.core.models.niche import Niche
from corp.core.models.niche_candidate import NicheCandidate, NicheCandidateStatus
from corp.core.models.workflow import ResearchRun
from corp.workers.adapters.base import AdapterFamily, NormalizedContent, SourceAdapter
from corp.workers.intelligence.niche_discovery import (
    DiscoveryConfig,
    RecursiveNicheDiscovery,
    matched_exclusion,
)
from corp.workers.providers.capabilities import (
    DissatisfactionProvider,
    SolutionProvider,
    TrendProvider,
)
from corp.workers.providers.registry import LLMProvider

# ---------- Fakes ----------


class _FakeAdapter(SourceAdapter):
    """A minimal NICHE-family fake with no capability of its own; subclassed
    below for each capability under test."""

    def __init__(self, platform: str, items: list[NormalizedContent] | None = None) -> None:
        self._platform = platform
        self._items = items or []
        self.calls: list[str] = []

    @property
    def platform(self) -> str:
        return self._platform

    @property
    def family(self) -> AdapterFamily:
        return AdapterFamily.NICHE

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.COMPLIANT

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        self.calls.append(identifier)
        return self._items


class _FakeTrendAdapter(_FakeAdapter, TrendProvider):
    async def fetch_trend(self, query: str) -> list[NormalizedContent]:
        return await self.collect(query)


class _FakeTwoCapabilityAdapter(_FakeAdapter, SolutionProvider, DissatisfactionProvider):
    """Mirrors AppStore/Marketplace (T2): both methods delegate to one collect()."""

    async def fetch_solutions(self, query: str) -> list[NormalizedContent]:
        return await self.collect(query)

    async def fetch_dissatisfaction(self, query: str) -> list[NormalizedContent]:
        return await self.collect(query)


def _content(external_id: str, text: str, platform: str = "faketrend") -> NormalizedContent:
    return NormalizedContent(
        source_platform=platform,
        content_type="fixture",
        external_id=external_id,
        text=text,
        timestamp=datetime.now(tz=UTC),
        access_method=AccessMethod.OPEN,
        compliance_status=ComplianceStatus.COMPLIANT,
    )


class ScriptedProvider(LLMProvider):
    """Returns a scripted niches-list response keyed by a substring of the
    prompt (the topic/keyword under test). Records every prompt it saw."""

    def __init__(self, script: dict[str, dict[str, Any]]) -> None:
        self._script = script
        self.prompts: list[str] = []

    @property
    def model_name(self) -> str:
        return "fake-synthesizer"

    def models_used(self) -> set[str]:
        return {"fake-synthesizer"}

    async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.prompts.append(prompt)
        for key, response in self._script.items():
            if key in prompt:
                return response
        return {"niches": []}


def _niche(name: str, terms: list[str], specific_enough: bool) -> dict[str, Any]:
    return {
        "name": name,
        "description": f"{name} description",
        "specific_enough": specific_enough,
        "evidence_terms": terms,
    }


async def _make_campaign(session: AsyncSession) -> Campaign:
    campaign = Campaign(name="T3 Test Campaign")
    session.add(campaign)
    await session.flush()
    return campaign


def _config(**overrides: Any) -> DiscoveryConfig:
    base = DiscoveryConfig(
        max_depth=3,
        breadth_depth_0=15,
        breadth_per_branch=10,
        recheck_days=90,
        max_evidence_texts=40,
        max_text_chars=300,
        exclusions={
            "adult_gambling_vice": ["sports betting", "online casino"],
            "illegal": ["buy drugs"],
        },
    )
    return dataclasses.replace(base, **overrides)


# ---------- matched_exclusion (unit-level, no DB) ----------


def test_matched_exclusion_hits():
    exclusions = {"adult_gambling_vice": ["sports betting"]}
    assert matched_exclusion("Best Sports Betting Strategies", exclusions) == "adult_gambling_vice"


def test_matched_exclusion_no_hit():
    exclusions = {"adult_gambling_vice": ["sports betting"]}
    assert matched_exclusion("Home Espresso Machines", exclusions) is None


# ---------- Depth / breadth caps ----------


@pytest.mark.asyncio
async def test_breadth_capped_at_depth_zero(clean_db: AsyncSession, monkeypatch):
    session = clean_db
    campaign = await _make_campaign(session)

    evidence_items = [_content(f"item{i}", f"evidence about topic {i}") for i in range(5)]
    fake = _FakeTrendAdapter("faketrend", evidence_items)
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", lambda platform: fake
    )

    # 20 candidates offered, only breadth_depth_0=3 should survive.
    niches = [_niche(f"Niche {i}", [f"topic {i}"], specific_enough=True) for i in range(20)]
    provider = ScriptedProvider({"broad topic": {"niches": niches}})

    discovery = RecursiveNicheDiscovery(
        session, provider, rules_path="unused", config=_config(breadth_depth_0=3)
    )
    await discovery.discover(campaign.id, "broad topic")

    result = await session.execute(
        select(NicheCandidate).where(NicheCandidate.campaign_id == campaign.id)
    )
    candidates = result.scalars().all()
    assert len(candidates) == 3


@pytest.mark.asyncio
async def test_depth_hard_cap_stops_recursion(clean_db: AsyncSession, monkeypatch):
    """A chain that is never 'specific_enough' must still stop at max_depth,
    and the deepest candidate must not be left stuck in DRILLING status."""
    session = clean_db
    campaign = await _make_campaign(session)

    evidence_items = [_content("e1", "evidence about drilling")]
    fake = _FakeTrendAdapter("faketrend", evidence_items)
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", lambda platform: fake
    )

    # Every level returns exactly one niche, never specific enough -> forces
    # max-depth recursion at every level.
    def _script_for(label: str) -> dict[str, Any]:
        return {"niches": [_niche(label, ["drilling"], specific_enough=False)]}

    provider = ScriptedProvider(
        {
            "Topic: root": _script_for("Level One"),
            "Topic: Level One": _script_for("Level Two"),
            "Topic: Level Two": _script_for("Level Three"),
            "Topic: Level Three": _script_for("Level Four"),
        }
    )

    discovery = RecursiveNicheDiscovery(
        session, provider, rules_path="unused", config=_config(max_depth=3)
    )
    await discovery.discover(campaign.id, "root")

    result = await session.execute(
        select(NicheCandidate)
        .where(NicheCandidate.campaign_id == campaign.id)
        .order_by(NicheCandidate.depth)
    )
    candidates = result.scalars().all()
    depths = [c.depth for c in candidates]
    assert depths == [0, 1, 2, 3]
    assert max(depths) == 3
    # The depth-3 candidate hit the hard cap while still not specific_enough
    # -- must be released back to STAGED, never left DRILLING.
    deepest = candidates[-1]
    assert deepest.status == NicheCandidateStatus.STAGED
    assert deepest.label == "Level Four"


@pytest.mark.asyncio
async def test_specific_enough_stops_recursion_early(clean_db: AsyncSession, monkeypatch):
    session = clean_db
    campaign = await _make_campaign(session)

    fake = _FakeTrendAdapter("faketrend", [_content("e1", "evidence about espresso")])
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", lambda platform: fake
    )

    provider = ScriptedProvider(
        {"Topic: coffee": {"niches": [_niche("Home Espresso", ["espresso"], specific_enough=True)]}}
    )
    discovery = RecursiveNicheDiscovery(session, provider, rules_path="unused", config=_config())
    await discovery.discover(campaign.id, "coffee")

    result = await session.execute(
        select(NicheCandidate).where(NicheCandidate.campaign_id == campaign.id)
    )
    candidates = result.scalars().all()
    assert len(candidates) == 1
    assert candidates[0].status == NicheCandidateStatus.STAGED
    assert candidates[0].parent_candidate_id is None
    assert candidates[0].depth == 0


# ---------- Exclusion matching ----------


@pytest.mark.asyncio
async def test_excluded_keyword_never_collects_evidence(clean_db: AsyncSession, monkeypatch):
    session = clean_db
    campaign = await _make_campaign(session)

    fake = _FakeTrendAdapter("faketrend", [_content("e1", "evidence")])
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", lambda platform: fake
    )
    provider = ScriptedProvider({})

    discovery = RecursiveNicheDiscovery(session, provider, rules_path="unused", config=_config())
    await discovery.discover(campaign.id, "sports betting strategies")

    assert fake.calls == []  # never even queried
    assert provider.prompts == []  # never even asked the LLM
    result = await session.execute(
        select(NicheCandidate).where(NicheCandidate.campaign_id == campaign.id)
    )
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_excluded_candidate_rejected_and_never_recurses(
    clean_db: AsyncSession, monkeypatch
):
    session = clean_db
    campaign = await _make_campaign(session)

    fake = _FakeTrendAdapter("faketrend", [_content("e1", "evidence about gambling odds")])
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", lambda platform: fake
    )

    provider = ScriptedProvider(
        {
            "Topic: hobbies": {
                "niches": [
                    _niche("Sports Betting Odds", ["gambling odds"], specific_enough=False)
                ]
            },
            # If recursion wrongly happened, this would be consulted next.
            "Topic: Sports Betting Odds": {
                "niches": [_niche("Should Never Exist", ["never"], specific_enough=True)]
            },
        }
    )
    discovery = RecursiveNicheDiscovery(session, provider, rules_path="unused", config=_config())
    await discovery.discover(campaign.id, "hobbies")

    result = await session.execute(
        select(NicheCandidate).where(NicheCandidate.campaign_id == campaign.id)
    )
    candidates = result.scalars().all()
    assert len(candidates) == 1
    rejected = candidates[0]
    assert rejected.status == NicheCandidateStatus.REJECTED
    assert rejected.extra == {"excluded_category": "adult_gambling_vice"}
    # Never recursed: the second script entry was never consulted.
    assert not any("Sports Betting Odds" in p and "hobbies" not in p for p in provider.prompts[1:])


# ---------- Registry freshness ----------


@pytest.mark.asyncio
async def test_fresh_niche_skips_entirely(clean_db: AsyncSession, monkeypatch):
    session = clean_db
    campaign = await _make_campaign(session)

    future = datetime.now(UTC) + timedelta(days=10)
    session.add(
        Niche(
            canonical_name="Home Espresso",
            last_researched_at=datetime.now(UTC),
            next_recheck_at=future,
        )
    )
    await session.flush()

    fake = _FakeTrendAdapter("faketrend", [_content("e1", "evidence")])
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", lambda platform: fake
    )
    provider = ScriptedProvider({})

    discovery = RecursiveNicheDiscovery(session, provider, rules_path="unused", config=_config())
    await discovery.discover(campaign.id, "Home Espresso")

    assert fake.calls == []
    assert provider.prompts == []


@pytest.mark.asyncio
async def test_stale_niche_does_not_skip(clean_db: AsyncSession, monkeypatch):
    session = clean_db
    campaign = await _make_campaign(session)

    past = datetime.now(UTC) - timedelta(days=1)
    session.add(
        Niche(
            canonical_name="Home Espresso",
            last_researched_at=datetime.now(UTC) - timedelta(days=91),
            next_recheck_at=past,
        )
    )
    await session.flush()

    fake = _FakeTrendAdapter("faketrend", [_content("e1", "evidence about espresso")])
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", lambda platform: fake
    )
    provider = ScriptedProvider(
        {"Topic: Home Espresso": {"niches": [_niche("Espresso Machines", ["espresso"], True)]}}
    )

    discovery = RecursiveNicheDiscovery(session, provider, rules_path="unused", config=_config())
    await discovery.discover(campaign.id, "Home Espresso")

    # The monkeypatch returns this one fake for every NICHE_FAN_OUT_PLATFORMS
    # slot (it's the only fake configured), so it legitimately gets called
    # once per platform build -- what matters is every call used the right
    # keyword, and evidence dedup below collapses the result to one row.
    assert fake.calls
    assert set(fake.calls) == {"Home Espresso"}
    result = await session.execute(
        select(NicheCandidate).where(NicheCandidate.campaign_id == campaign.id)
    )
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_registry_check_does_not_treat_keyword_as_sql_wildcard_pattern(
    clean_db: AsyncSession, monkeypatch
):
    """Stage 8 review finding: an ilike(keyword) lookup with no escaping
    would treat '%'/'_' in the keyword as SQL wildcards. 'Home%Espresso'
    as a LIKE pattern matches 'Home Espresso' (% matches the space) --
    a false-positive registry hit that would wrongly skip real work. The
    fix (exact func.lower(...) comparison) must not match here."""
    session = clean_db
    campaign = await _make_campaign(session)

    session.add(
        Niche(
            canonical_name="Home Espresso",
            last_researched_at=datetime.now(UTC),
            next_recheck_at=datetime.now(UTC) + timedelta(days=10),
        )
    )
    await session.flush()

    fake = _FakeTrendAdapter("faketrend", [_content("e1", "evidence about home espresso")])
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", lambda platform: fake
    )
    provider = ScriptedProvider(
        {"Topic: Home%Espresso": {"niches": [_niche("Espresso Gear", ["espresso"], True)]}}
    )

    discovery = RecursiveNicheDiscovery(session, provider, rules_path="unused", config=_config())
    await discovery.discover(campaign.id, "Home%Espresso")

    # A literal '%' in the keyword must not match the differently-spelled
    # existing niche -- drilling must proceed, not be skipped as "fresh".
    assert fake.calls


# ---------- Grounding: no evidence, no candidate ----------


@pytest.mark.asyncio
async def test_ungrounded_niche_dropped(clean_db: AsyncSession, monkeypatch):
    session = clean_db
    campaign = await _make_campaign(session)

    fake = _FakeTrendAdapter("faketrend", [_content("e1", "evidence about espresso")])
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", lambda platform: fake
    )
    # Cited term never appears in the evidence -> not grounded -> dropped.
    provider = ScriptedProvider(
        {
            "Topic: coffee": {
                "niches": [_niche("Invented Niche", ["nonexistent term"], specific_enough=True)]
            }
        }
    )
    discovery = RecursiveNicheDiscovery(session, provider, rules_path="unused", config=_config())
    await discovery.discover(campaign.id, "coffee")

    result = await session.execute(
        select(NicheCandidate).where(NicheCandidate.campaign_id == campaign.id)
    )
    assert result.scalars().all() == []


# ---------- Multi-capability adapter: intentional two-lens duplication ----------


@pytest.mark.asyncio
async def test_two_capability_adapter_persists_once_per_evidence_type(
    clean_db: AsyncSession, monkeypatch
):
    session = clean_db
    campaign = await _make_campaign(session)

    item = _content("listing_1", "a template that sells well", platform="fakemarket")
    fake = _FakeTwoCapabilityAdapter("fakemarket", [item])
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", lambda platform: fake
    )
    provider = ScriptedProvider(
        {"Topic: templates": {"niches": [_niche("Template Business", ["template"], True)]}}
    )

    discovery = RecursiveNicheDiscovery(session, provider, rules_path="unused", config=_config())
    await discovery.discover(campaign.id, "templates")

    result = await session.execute(
        select(Evidence).where(Evidence.source_platform == "fakemarket")
    )
    rows = result.scalars().all()
    # Same external_id, two distinct evidence_type values -- not four, not one.
    assert len(rows) == 2
    assert {r.evidence_type for r in rows} == {EvidenceType.SOLUTION, EvidenceType.DISSATISFACTION}
    assert {r.source_id for r in rows} == {"listing_1"}


@pytest.mark.asyncio
async def test_campaign_not_found_raises(clean_db: AsyncSession):
    provider = ScriptedProvider({})
    discovery = RecursiveNicheDiscovery(clean_db, provider, rules_path="unused", config=_config())
    with pytest.raises(ValueError, match="Campaign not found"):
        await discovery.discover("does-not-exist", "topic")


# ---------- research_more (CORP1 Stage 5, T8) ────────────────────────


@pytest.mark.asyncio
async def test_research_more_anchors_at_parent_candidate_depth_plus_one(
    clean_db: AsyncSession, monkeypatch
):
    session = clean_db
    campaign = await _make_campaign(session)

    niche = Niche(canonical_name="Home Espresso", depth=0)
    session.add(niche)
    await session.flush()
    promoted = NicheCandidate(
        campaign_id=campaign.id,
        research_run_id=(await _make_campaign_run(session, campaign.id)).id,
        label="Home Espresso",
        naming_method="llm",
        evidence_count=1,
        source_count=1,
        author_count=1,
        depth=1,
        status=NicheCandidateStatus.PROMOTED,
        niche_id=niche.id,
    )
    session.add(promoted)
    await session.flush()

    fake = _FakeTrendAdapter("faketrend", [_content("e1", "evidence about espresso machines")])
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", lambda platform: fake
    )
    provider = ScriptedProvider(
        {
            "Topic: Home Espresso": {
                "niches": [_niche("Espresso Machine Buying Guide", ["espresso"], True)]
            }
        }
    )
    discovery = RecursiveNicheDiscovery(session, provider, rules_path="unused", config=_config())
    run = await discovery.research_more(niche.id, campaign.id)

    assert run.niche_id == niche.id
    assert run.campaign_id == campaign.id
    result = await session.execute(
        select(NicheCandidate).where(NicheCandidate.research_run_id == run.id)
    )
    children = result.scalars().all()
    assert len(children) == 1
    assert children[0].parent_candidate_id == promoted.id
    assert children[0].depth == 2  # promoted.depth (1) + 1


@pytest.mark.asyncio
async def test_research_more_ignores_a_more_recent_merged_candidate(
    clean_db: AsyncSession, monkeypatch
):
    """Stage 8 review finding: NicheCandidate.niche_id is set by BOTH the
    PROMOTED branch of canonicalization (this candidate created the niche)
    and the MERGED branch (some other candidate, possibly from an
    unrelated campaign/drill run, was folded into this niche). A more
    recent MERGED row for the same niche must never be picked as the
    depth+1 anchor -- only the PROMOTED one reflects this niche's own
    drill lineage."""
    session = clean_db
    campaign = await _make_campaign(session)
    other_campaign = await _make_campaign(session)

    niche = Niche(canonical_name="Home Espresso", depth=0)
    session.add(niche)
    await session.flush()

    run_a = await _make_campaign_run(session, campaign.id)
    promoted = NicheCandidate(
        campaign_id=campaign.id,
        research_run_id=run_a.id,
        label="Home Espresso",
        naming_method="llm",
        evidence_count=1,
        source_count=1,
        author_count=1,
        depth=1,
        status=NicheCandidateStatus.PROMOTED,
        niche_id=niche.id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    session.add(promoted)
    await session.flush()

    # A later, unrelated candidate from a different campaign that merged
    # into the same niche, at a completely different (deeper) depth.
    run_b = await _make_campaign_run(session, other_campaign.id)
    merged = NicheCandidate(
        campaign_id=other_campaign.id,
        research_run_id=run_b.id,
        label="Espresso At Home",
        naming_method="llm",
        evidence_count=1,
        source_count=1,
        author_count=1,
        depth=3,
        status=NicheCandidateStatus.MERGED,
        niche_id=niche.id,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    session.add(merged)
    await session.flush()

    fake = _FakeTrendAdapter("faketrend", [_content("e1", "evidence about espresso machines")])
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", lambda platform: fake
    )
    provider = ScriptedProvider(
        {
            "Topic: Home Espresso": {
                "niches": [_niche("Espresso Machine Buying Guide", ["espresso"], True)]
            }
        }
    )
    discovery = RecursiveNicheDiscovery(session, provider, rules_path="unused", config=_config())
    run = await discovery.research_more(niche.id, campaign.id)

    result = await session.execute(
        select(NicheCandidate).where(NicheCandidate.research_run_id == run.id)
    )
    children = result.scalars().all()
    assert len(children) == 1
    # Anchored on the PROMOTED candidate (depth 1 -> 2), never the more
    # recent MERGED one (which would have wrongly given depth 4).
    assert children[0].parent_candidate_id == promoted.id
    assert children[0].depth == 2


@pytest.mark.asyncio
async def test_research_more_falls_back_to_niche_depth_with_no_candidate_lineage(
    clean_db: AsyncSession, monkeypatch
):
    """A niche seeded with no traceable NicheCandidate (e.g. created outside
    the discovery pipeline) still works: depth falls back to niche.depth + 1
    with no parent anchor, rather than raising."""
    session = clean_db
    campaign = await _make_campaign(session)
    niche = Niche(canonical_name="Sim Racing", depth=2)
    session.add(niche)
    await session.flush()

    fake = _FakeTrendAdapter("faketrend", [_content("e1", "evidence about sim racing rigs")])
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", lambda platform: fake
    )
    provider = ScriptedProvider(
        {"Topic: Sim Racing": {"niches": [_niche("Sim Racing Rigs", ["sim racing"], True)]}}
    )
    discovery = RecursiveNicheDiscovery(session, provider, rules_path="unused", config=_config())
    run = await discovery.research_more(niche.id, campaign.id)

    result = await session.execute(
        select(NicheCandidate).where(NicheCandidate.research_run_id == run.id)
    )
    children = result.scalars().all()
    assert len(children) == 1
    assert children[0].parent_candidate_id is None
    assert children[0].depth == 3  # niche.depth (2) + 1


@pytest.mark.asyncio
async def test_research_more_bypasses_registry_freshness_check(
    clean_db: AsyncSession, monkeypatch
):
    """A human explicitly asking to research this niche again right now
    must not be silently no-op'd by the same-day registry freshness skip
    that discover() applies during normal auto-recursion."""
    session = clean_db
    campaign = await _make_campaign(session)
    niche = Niche(
        canonical_name="Home Espresso",
        depth=0,
        last_researched_at=datetime.now(UTC),
        next_recheck_at=datetime.now(UTC) + timedelta(days=10),
    )
    session.add(niche)
    await session.flush()

    fake = _FakeTrendAdapter("faketrend", [_content("e1", "evidence about espresso")])
    monkeypatch.setattr(
        "corp.workers.intelligence.niche_discovery.build_adapter", lambda platform: fake
    )
    provider = ScriptedProvider(
        {"Topic: Home Espresso": {"niches": [_niche("Espresso Gear", ["espresso"], True)]}}
    )
    discovery = RecursiveNicheDiscovery(session, provider, rules_path="unused", config=_config())
    await discovery.research_more(niche.id, campaign.id)

    # discover() with the same fresh niche would have skipped entirely
    # (see test_fresh_niche_skips_entirely) -- research_more must not.
    assert fake.calls
    assert provider.prompts


@pytest.mark.asyncio
async def test_research_more_niche_not_found_raises(clean_db: AsyncSession):
    campaign = await _make_campaign(clean_db)
    provider = ScriptedProvider({})
    discovery = RecursiveNicheDiscovery(clean_db, provider, rules_path="unused", config=_config())
    with pytest.raises(ValueError, match="Niche not found"):
        await discovery.research_more("does-not-exist", campaign.id)


@pytest.mark.asyncio
async def test_research_more_campaign_not_found_raises(clean_db: AsyncSession):
    session = clean_db
    niche = Niche(canonical_name="Home Espresso", depth=0)
    session.add(niche)
    await session.flush()
    provider = ScriptedProvider({})
    discovery = RecursiveNicheDiscovery(session, provider, rules_path="unused", config=_config())
    with pytest.raises(ValueError, match="Campaign not found"):
        await discovery.research_more(niche.id, "does-not-exist")


async def _make_campaign_run(session: AsyncSession, campaign_id: str) -> ResearchRun:
    run = ResearchRun(campaign_id=campaign_id, status="completed")
    session.add(run)
    await session.flush()
    return run
