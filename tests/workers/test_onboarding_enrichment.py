"""No-DB unit tests for the onboarding subscriber-count enrichment path.

These exercise the helpers that don't touch the DB session, so a real
Postgres is not needed. The DB-backed flow is covered by
tests/integration/test_creator_onboarding.py.
"""

from unittest.mock import AsyncMock

from corp.workers.acquisition.creator_onboarding import (
    CreatorOnboarder,
    OnboardConfig,
    _is_enrichable_channel_id,
)


class _Niche:
    def __init__(self, name: str) -> None:
        self.id = name
        self.canonical_name = name


def _onboarder(enricher=None, **cfg) -> CreatorOnboarder:
    # session is unused by the helpers under test.
    return CreatorOnboarder(
        adapter=object(),
        session=object(),
        config=OnboardConfig(**cfg),
        enricher=enricher,
    )


# ── enrichable id check ──────────────────────────────────────────────


def test_is_enrichable_channel_id():
    assert _is_enrichable_channel_id("UC" + "x" * 22)      # 24 chars
    assert not _is_enrichable_channel_id("@handle")
    assert not _is_enrichable_channel_id("Display Name")
    assert not _is_enrichable_channel_id("UCtooshort")


# ── _enrich_all: one deduplicated, batched lookup ────────────────────


async def test_enrich_all_dedups_across_niches():
    uc1 = "UC" + "a" * 22
    uc2 = "UC" + "b" * 22
    enricher = AsyncMock()
    enricher.get_subscriber_counts = AsyncMock(return_value={uc1: 50_000, uc2: 20_000})

    onboarder = _onboarder(enricher=enricher)
    niche_channels = [
        (_Niche("alpha"), {uc1: {"name": "A"}, uc2: {"name": "B"}}),
        (_Niche("beta"), {uc1: {"name": "A"}, "@handleonly": {"name": "C"}}),
    ]

    counts = await onboarder._enrich_all(niche_channels)

    # uc1 appears in both niches but must be requested once; @handle is not enrichable.
    enricher.get_subscriber_counts.assert_awaited_once_with([uc1, uc2])
    assert counts == {uc1: 50_000, uc2: 20_000}


async def test_enrich_all_no_enricher_returns_empty():
    onboarder = _onboarder(enricher=None)
    counts = await onboarder._enrich_all([(_Niche("x"), {"UC" + "a" * 22: {}})])
    assert counts == {}


async def test_enrich_all_no_enrichable_ids_skips_call():
    enricher = AsyncMock()
    enricher.get_subscriber_counts = AsyncMock(return_value={})
    onboarder = _onboarder(enricher=enricher)

    counts = await onboarder._enrich_all([(_Niche("x"), {"@handle": {}, "Name": {}})])

    assert counts == {}
    enricher.get_subscriber_counts.assert_not_awaited()


async def test_enrich_all_failure_is_graceful():
    enricher = AsyncMock()
    enricher.get_subscriber_counts = AsyncMock(side_effect=RuntimeError("quota exceeded"))
    onboarder = _onboarder(enricher=enricher)

    counts = await onboarder._enrich_all([(_Niche("x"), {"UC" + "a" * 22: {}})])

    assert counts == {}  # onboarding proceeds without counts, never crashes


# ── _filter_and_cap: enriched counts drive the band filter ───────────


def test_filter_and_cap_uses_enriched_counts_over_ytdlp():
    uc = "UC" + "a" * 22
    onboarder = _onboarder(min_followers=10_000, max_followers=200_000)
    raw = {uc: {"name": "A", "follower_count": None}}  # yt-dlp had no count

    kept = onboarder._filter_and_cap(raw, {uc: 50_000})

    assert uc in kept
    assert kept[uc]["follower_count"] == 50_000


def test_filter_and_cap_band_excludes_out_of_range():
    small, good, big, unknown = (
        "UC" + "a" * 22, "UC" + "b" * 22, "UC" + "c" * 22, "UC" + "d" * 22,
    )
    onboarder = _onboarder(min_followers=10_000, max_followers=200_000)
    raw = {cid: {"name": cid} for cid in (small, good, big, unknown)}
    counts = {small: 100, good: 50_000, big: 5_000_000}  # unknown absent

    kept = onboarder._filter_and_cap(raw, counts)

    # good is in band; unknown (no count) never blocks; small/big excluded.
    assert set(kept) == {good, unknown}


def test_filter_and_cap_respects_max():
    onboarder = _onboarder(max_creators_per_niche=2)
    raw = {f"UC{c * 22}": {"name": c} for c in "abcd"}

    kept = onboarder._filter_and_cap(raw, {})

    assert len(kept) == 2


def test_filter_and_cap_falls_back_to_ytdlp_count_without_enricher():
    uc = "UC" + "a" * 22
    onboarder = _onboarder(min_followers=10_000, max_followers=200_000)
    raw = {uc: {"name": "A", "follower_count": 500}}  # below band, from yt-dlp

    kept = onboarder._filter_and_cap(raw, {})  # no enrichment happened

    assert kept == {}
