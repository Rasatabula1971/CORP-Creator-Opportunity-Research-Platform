"""Tests for adapter registry selection — especially search vs. collection."""

import pytest

from corp.config import Settings
from corp.workers.adapters.marketplace import MarketplaceAdapter
from corp.workers.adapters.registry import (
    AdapterConfigError,
    build_adapter,
    build_search_adapter,
)
from corp.workers.adapters.youtube import YouTubeAdapter
from corp.workers.adapters.ytdlp import YtDlpAdapter


def test_build_search_adapter_uses_ytdlp_without_key():
    cfg = Settings(youtube_api_key="")
    adapter = build_search_adapter("youtube", cfg)
    assert isinstance(adapter, YtDlpAdapter)
    assert adapter.platform == "youtube"


def test_build_search_adapter_uses_ytdlp_even_with_key():
    # Discovery search needs yt-dlp's ``ytsearchN:`` syntax; the YouTube Data API
    # adapter resolves a single channel handle and would fail on a search query.
    # A configured API key must NOT flip search to the Data API adapter.
    cfg = Settings(youtube_api_key="AIza-fake-key")
    adapter = build_search_adapter("youtube", cfg)
    assert isinstance(adapter, YtDlpAdapter)


def test_build_adapter_uses_youtube_api_with_key():
    # Contrast: single-channel collection DOES use the Data API when a key is set.
    cfg = Settings(youtube_api_key="AIza-fake-key")
    adapter = build_adapter("youtube", cfg)
    assert isinstance(adapter, YouTubeAdapter)


def test_build_search_adapter_tiktok():
    cfg = Settings()
    adapter = build_search_adapter("tiktok", cfg)
    assert isinstance(adapter, YtDlpAdapter)
    assert adapter.platform == "tiktok"


def test_build_search_adapter_unsupported_platform():
    cfg = Settings()
    with pytest.raises(AdapterConfigError):
        build_search_adapter("stackexchange", cfg)


# ── Marketplace sites that cannot answer are left out (ADR-0066) ──────


def test_marketplace_drops_udemy_and_keyless_etsy():
    cfg = Settings(marketplace_sites="gumroad,etsy,udemy", etsy_api_key="")
    adapter = build_adapter("marketplace", cfg)
    assert isinstance(adapter, MarketplaceAdapter)
    assert adapter._marketplaces == ["gumroad"]


def test_marketplace_keeps_etsy_when_a_key_is_set():
    cfg = Settings(marketplace_sites="gumroad,etsy", etsy_api_key="kt_test")
    adapter = build_adapter("marketplace", cfg)
    assert isinstance(adapter, MarketplaceAdapter)
    assert adapter._marketplaces == ["gumroad", "etsy"]


def test_marketplace_with_no_usable_site_is_a_config_error():
    cfg = Settings(marketplace_sites="udemy,etsy", etsy_api_key="")
    with pytest.raises(AdapterConfigError, match="no usable marketplace"):
        build_adapter("marketplace", cfg)


def test_default_marketplace_sites_are_gumroad_only():
    # Udemy's API is dead and Etsy needs an approved developer app that is not
    # currently available, so neither is queried by default (ADR-0066).
    sites = Settings().marketplace_sites
    assert "udemy" not in sites
    assert "etsy" not in sites
    assert "gumroad" in sites
    assert "crowdfunding" in Settings().discovery_disabled_sources


def test_blocked_marketplace_notice_is_logged_once_per_process(caplog):
    """The adapter is rebuilt per keyword; the notice must not repeat per build."""
    import logging

    from corp.workers.adapters import registry

    registry._warned_marketplace_sites.clear()
    cfg = Settings(marketplace_sites="gumroad,etsy,udemy", etsy_api_key="")
    with caplog.at_level(logging.WARNING, logger="corp.workers.adapters.registry"):
        build_adapter("marketplace", cfg)
        build_adapter("marketplace", cfg)
        build_adapter("marketplace", cfg)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert sorted(r.getMessage().split(" ")[2] for r in warnings) == ["'etsy'", "'udemy'"]
