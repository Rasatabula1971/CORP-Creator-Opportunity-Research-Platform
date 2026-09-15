"""Tests for adapter registry selection — especially search vs. collection."""

import pytest

from corp.config import Settings
from corp.workers.adapters.registry import (
    AdapterConfigError,
    build_search_adapter,
)
from corp.workers.adapters.ytdlp import YtDlpAdapter
from corp.workers.adapters.youtube import YouTubeAdapter
from corp.workers.adapters.registry import build_adapter


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
