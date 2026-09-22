"""Provenance Invariant (CORP1 Stage 4): every legacy collect() row must get an
evidence_type, so the fallback platform → type map must cover every platform
string an adapter can emit, and must agree with the capability interface(s)
that adapter actually implements."""

import pytest

from corp.core.models.evidence import (
    EvidenceType,
    infer_evidence_type,
    require_evidence_type,
)
from corp.workers.adapters.amazonreviews import AmazonReviewAdapter
from corp.workers.adapters.appstore import AppStoreAdapter
from corp.workers.adapters.crowdfunding import CrowdfundingAdapter
from corp.workers.adapters.googletrends import GoogleTrendsAdapter
from corp.workers.adapters.hackernews import HackerNewsAdapter
from corp.workers.adapters.marketplace import MarketplaceAdapter
from corp.workers.adapters.patreon_substack import PatreonSubstackAdapter
from corp.workers.adapters.reddit import RedditAdapter
from corp.workers.adapters.registry import KNOWN_PLATFORMS
from corp.workers.adapters.searchdemand import SearchDemandAdapter
from corp.workers.adapters.stackexchange import StackExchangeAdapter
from corp.workers.adapters.wikipedia import WikipediaAdapter
from corp.workers.adapters.youtube import YouTubeAdapter
from corp.workers.providers.capabilities import CAPABILITY_INTERFACES

_ADAPTER_PLATFORMS = [
    ("youtube", YouTubeAdapter),
    ("reddit", RedditAdapter),
    ("stackexchange", StackExchangeAdapter),
    ("searchdemand", SearchDemandAdapter),
    ("amazon_reviews", AmazonReviewAdapter),
    ("marketplace", MarketplaceAdapter),
    ("hackernews", HackerNewsAdapter),
    ("wikipedia", WikipediaAdapter),
    ("googletrends", GoogleTrendsAdapter),
    ("appstore", AppStoreAdapter),
    ("crowdfunding", CrowdfundingAdapter),
    ("patreon_substack", PatreonSubstackAdapter),
]


@pytest.mark.parametrize("platform", KNOWN_PLATFORMS)
def test_every_known_platform_has_an_evidence_type(platform: str) -> None:
    assert infer_evidence_type(platform) is not None, platform


@pytest.mark.parametrize(("platform", "adapter_cls"), _ADAPTER_PLATFORMS)
def test_fallback_type_matches_a_declared_capability(
    platform: str, adapter_cls: type
) -> None:
    declared = {
        iface.evidence_type
        for iface in CAPABILITY_INTERFACES
        if issubclass(adapter_cls, iface)
    }
    assert declared, f"{adapter_cls.__name__} implements no capability interface"
    assert infer_evidence_type(platform) in declared


def test_lookup_is_case_insensitive() -> None:
    assert infer_evidence_type("GoogleTrends") is EvidenceType.TREND


def test_unknown_platform_returns_none() -> None:
    assert infer_evidence_type("no_such_platform") is None


def test_require_raises_for_unknown_platform_naming_it() -> None:
    with pytest.raises(ValueError, match="no_such_platform"):
        require_evidence_type("no_such_platform")
    assert require_evidence_type("Reddit") is EvidenceType.PROBLEM
