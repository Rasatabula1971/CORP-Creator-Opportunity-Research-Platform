"""Unit tests for the yt-dlp metadata adapter — extractor faked, no network."""

import pytest

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import AdapterFamily, SourceAdapter
from corp.workers.adapters.ytdlp import YtDlpAdapter


class FakeExtractor:
    """Answers extract_info from a url -> info table; records the opts it was built with."""

    def __init__(self, opts, table, calls):
        self.opts = opts
        self._table = table
        self._calls = calls

    def extract_info(self, url, download=False):
        self._calls.append((url, dict(self.opts)))
        value = self._table.get(url)
        if isinstance(value, Exception):
            raise value
        return value


def _adapter(table, calls=None, **kw) -> YtDlpAdapter:
    calls = calls if calls is not None else []
    return YtDlpAdapter(
        extractor_factory=lambda opts: FakeExtractor(opts, table, calls), **kw
    )


CHANNEL = "https://www.youtube.com/@maker/videos"
VID1 = "https://www.youtube.com/watch?v=v1"
VID2 = "https://www.youtube.com/shorts/v2"

LISTING = {
    "channel": "Maker Channel",
    "uploader_id": "@maker",
    "channel_follower_count": 123456,
    "description": "We build things",
    "channel_url": "https://www.youtube.com/@maker",
    "playlist_count": 2,
    "entries": [{"id": "v1", "url": VID1}, {"id": "v2", "url": VID2}, None],
}
INFO1 = {
    "id": "v1",
    "title": "How to fix a wobbly desk",
    "description": "Full walkthrough.",
    "uploader": "Maker Channel",
    "channel_id": "UCabc123",
    "uploader_id": "@maker",
    "channel_url": "https://www.youtube.com/@maker",
    "channel_follower_count": 4321,
    "timestamp": 1_700_000_000,
    "webpage_url": VID1,
    "view_count": 1000,
    "like_count": 50,
    "comment_count": 7,
    "tags": ["diy"],
    "comments": [
        {"id": "c1", "text": "where can I buy the brackets?", "author": "a", "parent": "root",
         "like_count": 3, "timestamp": 1_700_000_100},
        {"id": "c2", "text": "same question", "author": "b", "parent": "c1", "like_count": 0},
    ],
}
INFO2 = {"id": "v2", "title": "Quick tip", "upload_date": "20240102", "webpage_url": VID2}


@pytest.fixture(autouse=True)
def no_captions(monkeypatch):
    monkeypatch.setattr(
        "corp.workers.adapters.ytdlp.fetch_youtube_caption", lambda *a, **k: None
    )


SEARCH = "ytsearch2:wobbly desk fix"
SEARCH_LISTING = {
    # What yt-dlp returns for a search: a synthetic playlist titled with the
    # query, no channel/uploader behind it.
    "id": "wobbly desk fix",
    "title": "wobbly desk fix",
    "extractor_key": "YoutubeSearch",
    "entries": [{"id": "v1", "url": VID1}, {"id": "v2", "url": VID2}],
}


def test_is_search_recognises_ytdlp_search_syntax():
    assert YtDlpAdapter.is_search("ytsearch5:espresso")
    assert YtDlpAdapter.is_search("  YTSEARCHDATE3:espresso  ")
    assert not YtDlpAdapter.is_search("@maker")
    assert not YtDlpAdapter.is_search("UCabc")
    assert not YtDlpAdapter.is_search("https://www.youtube.com/@maker")


def test_search_identifier_passes_through_to_ytdlp_unchanged():
    adapter = _adapter({SEARCH: SEARCH_LISTING, VID1: INFO1, VID2: INFO2})
    assert adapter.profile_url(SEARCH) == SEARCH
    assert adapter.profile_url("@maker") == CHANNEL


async def test_search_collect_yields_videos_but_no_profile():
    """A search spans many channels, so it must never emit a creator profile
    item — the query string is not a creator."""
    calls = []
    adapter = _adapter({SEARCH: SEARCH_LISTING, VID1: INFO1, VID2: INFO2}, calls)
    items = await adapter.collect(SEARCH)

    assert calls[0][0] == SEARCH  # the listing call went to yt-dlp as a search
    types = [i.content_type for i in items]
    assert "profile" not in types
    assert types.count("video") + types.count("short") == 2
    assert {i.external_id for i in items} == {"v1", "v2"}
    assert all(i.source_platform == "youtube" for i in items)
    # Without a profile item, the channel size must ride on the video so the
    # ecosystem estimator can band creators without a YouTube API key.
    v1 = next(i for i in items if i.external_id == "v1")
    assert v1.metadata["follower_count"] == 4321


async def test_channel_collect_still_emits_profile():
    """Regression: the non-search path is unchanged."""
    items = await _adapter({CHANNEL: LISTING, VID1: INFO1, VID2: INFO2}).collect("@maker")
    assert items[0].content_type == "profile"
    assert items[0].metadata["follower_count"] == 123456


def test_contract_and_tags():
    a = YtDlpAdapter(extractor_factory=lambda o: None)
    assert isinstance(a, SourceAdapter)
    assert a.platform == "youtube"
    assert a.family == AdapterFamily.CREATOR_BOUND
    assert a.access_method == AccessMethod.OPEN
    assert a.compliance_status == ComplianceStatus.VERIFY
    with pytest.raises(ValueError):
        YtDlpAdapter(platform="instagram")


@pytest.mark.parametrize(
    "platform, ident, expected",
    [
        ("youtube", "@maker", "https://www.youtube.com/@maker/videos"),
        ("youtube", "maker", "https://www.youtube.com/@maker/videos"),
        ("youtube", "UCabc123", "https://www.youtube.com/channel/UCabc123/videos"),
        ("youtube", "https://www.youtube.com/c/x", "https://www.youtube.com/c/x"),
        ("tiktok", "@dancer", "https://www.tiktok.com/@dancer"),
        ("tiktok", "dancer", "https://www.tiktok.com/@dancer"),
    ],
)
def test_profile_url(platform, ident, expected):
    a = YtDlpAdapter(platform=platform, extractor_factory=lambda o: None)
    assert a.profile_url(ident) == expected


@pytest.mark.parametrize(
    "platform, url",
    [
        ("youtube", "http://169.254.169.254/latest/meta-data/"),
        ("youtube", "https://internal.example/admin"),
        ("youtube", "https://tiktok.com/@dancer"),  # right shape, wrong platform
        ("tiktok", "https://www.youtube.com/@maker/videos"),
        ("tiktok", "http://localhost:8080/"),
    ],
)
def test_profile_url_rejects_urls_outside_platform_domain(platform, url):
    a = YtDlpAdapter(platform=platform, extractor_factory=lambda o: None)
    with pytest.raises(ValueError):
        a.profile_url(url)


@pytest.mark.parametrize(
    "platform, url",
    [
        ("youtube", "https://youtu.be/abc123"),
        ("youtube", "https://m.youtube.com/@maker"),
        ("tiktok", "https://vm.tiktok.com/@dancer"),
    ],
)
def test_profile_url_allows_platform_subdomains_and_short_domains(platform, url):
    a = YtDlpAdapter(platform=platform, extractor_factory=lambda o: None)
    assert a.profile_url(url) == url


async def test_collect_profile_videos_and_flat_then_full_opts():
    calls = []
    a = _adapter({CHANNEL: LISTING, VID1: INFO1, VID2: INFO2}, calls)
    items = await a.collect("@maker")

    types = [i.content_type for i in items]
    assert types == ["profile", "video", "short"]

    profile = items[0]
    assert profile.metadata["follower_count"] == 123456
    assert profile.metadata["handle"] == "@maker"
    assert profile.external_id == "profile_@maker"

    v1 = items[1]
    assert v1.external_id == "v1"
    assert v1.text.startswith("How to fix a wobbly desk\n\nFull walkthrough.")
    assert v1.metadata["view_count"] == 1000 and v1.metadata["comment_count"] == 7
    assert v1.timestamp is not None and v1.timestamp.year == 2023
    assert v1.metadata["title"] == "How to fix a wobbly desk"
    # Stable channel identity, not just the display name in `author` — this is
    # what downstream code (ecosystem_estimator, creator_onboarding) must use
    # to build a working profile URL later.
    assert v1.metadata["channel_id"] == "UCabc123"
    assert v1.metadata["channel_handle"] == "@maker"
    assert v1.metadata["channel_url"] == "https://www.youtube.com/@maker"

    v2 = items[2]
    assert v2.content_type == "short"
    assert v2.timestamp.isoformat().startswith("2024-01-02")

    # First call lists flat; per-video calls are full extractions.
    assert calls[0][0] == CHANNEL and calls[0][1]["extract_flat"] == "in_playlist"
    assert calls[1][0] == VID1 and "extract_flat" not in calls[1][1]
    assert all(c[1]["skip_download"] for c in calls)
    assert "getcomments" not in calls[1][1]


async def test_comments_off_by_default_and_tagged_when_on():
    a = _adapter({CHANNEL: LISTING, VID1: INFO1, VID2: INFO2})
    assert not [i for i in await a.collect("@maker") if i.content_type in ("comment", "reply")]

    calls = []
    a = _adapter({CHANNEL: LISTING, VID1: INFO1, VID2: INFO2}, calls, include_comments=True)
    items = await a.collect("@maker")
    comments = [i for i in items if i.content_type in ("comment", "reply")]
    assert [c.external_id for c in comments] == ["c1", "c2"]
    assert comments[0].content_type == "comment" and comments[0].parent_id == "v1"
    assert comments[1].content_type == "reply" and comments[1].parent_id == "c1"
    assert all(c.access_method == AccessMethod.VENDOR_SCRAPE for c in comments)
    assert all(c.compliance_status == ComplianceStatus.TOS_RISK for c in comments)
    assert calls[1][1]["getcomments"] is True


async def test_max_items_caps_entries():
    calls = []
    a = _adapter({CHANNEL: LISTING, VID1: INFO1, VID2: INFO2}, calls, max_items=1)
    items = await a.collect("@maker")
    assert [i.content_type for i in items] == ["profile", "video"]
    assert calls[0][1]["playlistend"] == 1


async def test_failed_video_is_skipped_not_fatal():
    a = _adapter({CHANNEL: LISTING, VID1: RuntimeError("private video"), VID2: INFO2})
    items = await a.collect("@maker")
    assert [i.external_id for i in items] == ["profile_@maker", "v2"]


async def test_none_info_from_ignoreerrors_is_skipped(monkeypatch):
    """With ``ignoreerrors`` yt-dlp returns None for a private/removed video
    instead of raising; that must not become a video with external_id "None"."""
    captioned: list[str] = []
    monkeypatch.setattr(
        "corp.workers.adapters.ytdlp.fetch_youtube_caption",
        lambda vid, *a, **k: captioned.append(vid),
    )
    a = _adapter({CHANNEL: LISTING, VID1: None, VID2: {"title": "no id"}})
    items = await a.collect("@maker")
    assert [i.external_id for i in items] == ["profile_@maker"]
    assert "None" not in {i.external_id for i in items}
    assert captioned == []


async def test_tiktok_items_are_shorts_with_music():
    profile = "https://www.tiktok.com/@dancer"
    video_url = "https://www.tiktok.com/@dancer/video/t1"
    listing = {
        "uploader": "Dancer",
        "follower_count": 900,
        "entries": [{"id": "t1", "url": video_url}],
    }
    info = {
        "id": "t1",
        "title": "spin",
        "track": "Cool Song",
        "webpage_url": video_url,
        "repost_count": 4,
    }
    a = _adapter({profile: listing, info["webpage_url"]: info}, platform="tiktok")
    items = await a.collect("@dancer")
    assert items[0].content_type == "profile" and items[0].metadata["follower_count"] == 900
    assert items[1].content_type == "short"
    assert items[1].metadata["music"] == "Cool Song"
    assert items[1].metadata["share_count"] == 4
