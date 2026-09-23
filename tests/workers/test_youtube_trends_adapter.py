"""Unit tests for the YouTube trending momentum adapter — API fully faked."""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.youtube import QuotaExceededError
from corp.workers.adapters.youtube_trends import (
    TrendChartUnavailableError,
    YouTubeTrendsAdapter,
    topic_terms,
)
from corp.workers.providers.capabilities import TrendProvider


def _http_error(status: int, reason: str) -> HttpError:
    resp = MagicMock()
    resp.status = status
    content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode("utf-8")
    return HttpError(resp, content)


def _video(vid: str, title: str, views: int, tags: list[str] | None = None, desc: str = ""):
    snippet: dict[str, Any] = {"title": title, "description": desc}
    if tags is not None:
        snippet["tags"] = tags
    return {"id": vid, "snippet": snippet, "statistics": {"viewCount": str(views)}}


class _Request:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeYouTube:
    """Stands in for googleapiclient's Resource. Records every call so tests
    can assert exactly how much quota a pass spends."""

    def __init__(
        self,
        categories: list[tuple[str, str, bool]],
        charts: dict[str, list[dict]] | dict[str, Exception],
        pages: dict[str, list[list[dict]]] | None = None,
        categories_error: Exception | None = None,
    ) -> None:
        self.categories = categories
        self.charts = charts
        self.pages = pages or {}
        self.categories_error = categories_error
        self.calls: list[tuple[str, dict]] = []

    def videoCategories(self):  # noqa: N802 — mirrors the client API
        outer = self

        class _Cats:
            def list(self, **kw):
                outer.calls.append(("videoCategories.list", kw))

                def run():
                    if outer.categories_error is not None:
                        raise outer.categories_error
                    return {
                        "items": [
                            {"id": cid, "snippet": {"title": title, "assignable": assignable}}
                            for cid, title, assignable in outer.categories
                        ]
                    }

                return _Request(run)

        return _Cats()

    def videos(self):
        outer = self

        class _Videos:
            def list(self, **kw):
                outer.calls.append(("videos.list", kw))
                cid = kw["videoCategoryId"]

                def run():
                    if cid in outer.pages:
                        token = kw.get("pageToken")
                        pages = outer.pages[cid]
                        idx = 0 if token is None else int(token)
                        out: dict[str, Any] = {"items": pages[idx]}
                        if idx + 1 < len(pages):
                            out["nextPageToken"] = str(idx + 1)
                        return out
                    chart = outer.charts.get(cid, [])
                    if isinstance(chart, Exception):
                        raise chart
                    return {"items": chart}

                return _Request(run)

        return _Videos()

    def chart_calls(self) -> int:
        return sum(1 for name, _ in self.calls if name == "videos.list")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _adapter(fake: FakeYouTube, **kw) -> YouTubeTrendsAdapter:
    kw.setdefault("requests_per_second", 0)  # no sleeping in tests
    return YouTubeTrendsAdapter(api_key="fake", service=fake, **kw)


CATS = [("26", "Howto & Style", True), ("2", "Autos & Vehicles", True)]


# ── Contract ─────────────────────────────────────────────────────────


def test_is_an_official_compliant_trend_provider():
    a = _adapter(FakeYouTube(CATS, {}))
    assert isinstance(a, TrendProvider)
    assert a.access_method == AccessMethod.OFFICIAL
    assert a.compliance_status == ComplianceStatus.COMPLIANT
    assert a.platform == "youtube_trends"


def test_constructing_the_adapter_spends_no_quota():
    fake = FakeYouTube(CATS, {})
    a = _adapter(fake)
    assert fake.calls == []
    assert a.quota_used == 0


# ── Matching ─────────────────────────────────────────────────────────


def test_topic_terms_drop_stopwords_and_fold_plurals():
    assert topic_terms("studying and productivity") == {"studying", "productivity"}
    assert topic_terms("board games") == {"board", "game"}
    assert topic_terms("3d printing") == {"3d", "printing"}
    assert topic_terms("and the of") == frozenset()


async def test_all_topic_words_must_appear():
    fake = FakeYouTube(CATS, {"26": [
        _video("a", "Beginner woodworking projects", 50_000),
        _video("b", "Personal stories from the road", 90_000),
    ]})
    a = _adapter(fake)
    assert await a.fetch_trend("personal finance") == []
    hits = await a.fetch_trend("woodworking")
    assert len(hits) == 1
    assert hits[0].metadata["matched_count"] == 1


async def test_matching_is_whole_word_not_substring():
    fake = FakeYouTube(CATS, {"26": [_video("a", "Greek yogurt breakfast bowls", 1_000_000)]})
    assert await _adapter(fake).fetch_trend("yoga") == []


async def test_plural_folding_matches_both_ways():
    fake = FakeYouTube(CATS, {"26": [_video("a", "Best Board Game of the Year", 200_000)]})
    hits = await _adapter(fake).fetch_trend("board games")
    assert hits and hits[0].metadata["matched_count"] == 1


async def test_tags_count_but_descriptions_do_not():
    """Descriptions are where sponsor copy lives — "sponsored by a personal
    finance app" is not momentum for personal finance."""
    fake = FakeYouTube(CATS, {"26": [
        _video("tagged", "My weekend", 10_000, tags=["Home Cooking", "recipes"]),
        _video("sponsored", "Unboxing", 10_000, desc="Sponsored by a personal finance app"),
    ]})
    a = _adapter(fake)
    assert (await a.fetch_trend("home cooking"))[0].metadata["matched_count"] == 1
    assert await a.fetch_trend("personal finance") == []


async def test_blank_topic_spends_nothing():
    fake = FakeYouTube(CATS, {})
    assert await _adapter(fake).fetch_trend("  and  ") == []
    assert fake.calls == []


# ── Scoring ──────────────────────────────────────────────────────────


async def test_score_is_on_the_scanners_0_to_100_scale_and_saturates():
    many = [_video(f"v{i}", f"Woodworking build {i}", 5_000_000) for i in range(40)]
    fake = FakeYouTube(CATS, {"26": many})
    score = (await _adapter(fake).fetch_trend("woodworking"))[0].metadata["avg_interest"]
    assert 99.0 <= score <= 100.0


async def test_more_views_means_more_momentum():
    small = FakeYouTube(CATS, {"26": [_video("a", "Woodworking tips", 1_000)]})
    big = FakeYouTube(CATS, {"26": [_video("a", "Woodworking tips", 5_000_000)]})
    s_small = (await _adapter(small).fetch_trend("woodworking"))[0].metadata["avg_interest"]
    s_big = (await _adapter(big).fetch_trend("woodworking"))[0].metadata["avg_interest"]
    assert 0 < s_small < s_big < 100


async def test_one_viral_video_does_not_swamp_several_solid_ones():
    viral = FakeYouTube(CATS, {"26": [_video("a", "Baking fail", 500_000_000)]})
    steady = FakeYouTube(CATS, {"26": [
        _video(f"b{i}", f"Baking bread {i}", 1_000_000) for i in range(4)
    ]})
    s_viral = (await _adapter(viral).fetch_trend("baking"))[0].metadata["avg_interest"]
    s_steady = (await _adapter(steady).fetch_trend("baking"))[0].metadata["avg_interest"]
    assert s_steady > s_viral


async def test_item_carries_provenance():
    fake = FakeYouTube(CATS, {"2": [_video("car1", "Car detailing on a budget", 300_000)]})
    item = (await _adapter(fake, region="gb").fetch_trend("car detailing"))[0]
    assert item.content_type == "interest"
    assert item.metadata["region"] == "GB"
    assert item.metadata["categories"] == ["Autos & Vehicles"]
    assert item.metadata["matched_videos"][0]["video_id"] == "car1"
    assert item.url == "https://www.youtube.com/watch?v=car1"
    assert "mostPopular" in item.metadata["source"]


# ── Quota: one chart pull, then local scoring ────────────────────────


async def test_scoring_many_topics_pulls_the_chart_once():
    fake = FakeYouTube(CATS, {"26": [_video("a", "Woodworking", 10)], "2": []})
    a = _adapter(fake)
    for topic in ["woodworking", "baking", "yoga", "automotive", "personal finance"]:
        await a.fetch_trend(topic)
    assert fake.chart_calls() == 2  # one page per category, total
    assert a.quota_used == 3  # 1 categories + 2 chart pages


async def test_only_assignable_categories_are_charted():
    cats = CATS + [("30", "Movies", False)]
    fake = FakeYouTube(cats, {"26": [], "2": []})
    await _adapter(fake).fetch_trend("anything")
    charted = {kw["videoCategoryId"] for name, kw in fake.calls if name == "videos.list"}
    assert charted == {"26", "2"}


async def test_chart_request_uses_the_official_most_popular_chart():
    fake = FakeYouTube(CATS, {"26": [], "2": []})
    await _adapter(fake, region="de").fetch_trend("anything")
    _, kw = next(c for c in fake.calls if c[0] == "videos.list")
    assert kw["chart"] == "mostPopular"
    assert kw["regionCode"] == "DE"
    assert kw["maxResults"] == 50


async def test_the_cache_expires_and_reloads():
    clock = Clock()
    fake = FakeYouTube(CATS, {"26": [], "2": []})
    a = _adapter(fake, clock=clock, cache_ttl_seconds=60)
    await a.fetch_trend("x")
    clock.now += 59
    await a.fetch_trend("x")
    assert fake.chart_calls() == 2
    clock.now += 2
    await a.fetch_trend("x")
    assert fake.chart_calls() == 4


async def test_pagination_follows_next_page_token_up_to_the_limit():
    fake = FakeYouTube(
        [("26", "Howto & Style", True)],
        {},
        pages={"26": [[_video("a", "Knitting 1", 1)], [_video("b", "Knitting 2", 1)],
                      [_video("c", "Knitting 3", 1)]]},
    )
    hits = await _adapter(fake, pages_per_category=2).fetch_trend("knitting")
    assert hits[0].metadata["matched_count"] == 2
    assert fake.chart_calls() == 2


async def test_a_video_in_two_categories_counts_once():
    dup = _video("same", "Van life camping build", 100_000)
    fake = FakeYouTube(CATS, {"26": [dup], "2": [dup]})
    hits = await _adapter(fake).fetch_trend("van life")
    assert hits[0].metadata["matched_count"] == 1


async def test_daily_quota_is_respected():
    fake = FakeYouTube(CATS, {"26": [], "2": []})
    a = _adapter(fake, daily_quota=2)
    with pytest.raises(TrendChartUnavailableError, match=QuotaExceededError.__name__):
        await a.fetch_trend("x")
    # Categories (1) + first chart (1) fit; the second chart is refused
    # before it executes, so spend stops exactly at the budget.
    assert a.quota_used == 2


# ── Failure handling ─────────────────────────────────────────────────


async def test_a_category_without_a_chart_is_skipped():
    fake = FakeYouTube(CATS, {
        "26": _http_error(404, "videoChartNotFound"),
        "2": [_video("a", "Motorcycles touring", 10_000)],
    })
    hits = await _adapter(fake).fetch_trend("motorcycles")
    assert hits and hits[0].metadata["matched_count"] == 1


async def test_quota_exhaustion_is_not_swallowed_as_a_missing_chart():
    fake = FakeYouTube(CATS, {"26": _http_error(403, "quotaExceeded")})
    with pytest.raises(TrendChartUnavailableError, match="quotaExceeded"):
        await _adapter(fake).fetch_trend("anything")
    assert fake.chart_calls() == 1, "a systemic error must stop the pull"


async def test_no_assignable_categories_is_an_error_not_an_empty_chart():
    fake = FakeYouTube([("30", "Movies", False)], {})
    with pytest.raises(TrendChartUnavailableError):
        await _adapter(fake).fetch_trend("anything")


async def test_a_failed_load_is_cached_so_an_outage_is_not_fifty_requests():
    clock = Clock()
    fake = FakeYouTube(CATS, {}, categories_error=_http_error(403, "forbidden"))
    a = _adapter(fake, clock=clock, failure_ttl_seconds=300)
    with pytest.raises(TrendChartUnavailableError, match="403"):
        await a.fetch_trend("woodworking")
    for topic in ["baking", "yoga", "fishing"]:
        with pytest.raises(TrendChartUnavailableError):
            await a.fetch_trend(topic)
    assert len(fake.calls) == 1, "later topics must not re-hit the API during the backoff"

    clock.now += 301
    fake.categories_error = None
    fake.charts = {"26": [], "2": []}
    assert await a.fetch_trend("pottery") == []  # recovered after the window
    assert len(fake.calls) == 4  # categories + two charts, once


# ── collect() ────────────────────────────────────────────────────────


async def test_collect_chart_returns_the_raw_corpus():
    fake = FakeYouTube(CATS, {"26": [_video("a", "One", 5)], "2": [_video("b", "Two", 7)]})
    items = await _adapter(fake).collect("chart")
    assert {i.external_id for i in items} == {"a", "b"}
    assert all(i.content_type == "video" for i in items)


async def test_collect_anything_else_scores_it_as_a_topic():
    fake = FakeYouTube(CATS, {"26": [_video("a", "Pottery wheel basics", 5)]})
    items = await _adapter(fake).collect("pottery")
    assert items[0].content_type == "interest"


# ── End to end with the scanner ──────────────────────────────────────


async def test_scanner_ranks_by_youtube_momentum(clean_db):
    from corp.workers.intelligence.niche_discovery import DiscoveryConfig
    from corp.workers.intelligence.trend_scan import TrendScanConfig, TrendScanner

    fake = FakeYouTube(CATS, {
        "26": [
            _video("w1", "Woodworking bench build", 2_000_000),
            _video("w2", "Woodworking joinery", 1_500_000),
            _video("b1", "Baking sourdough", 20_000),
        ],
        "2": [],
    })
    scanner = TrendScanner(
        clean_db,
        trend_provider=_adapter(fake),
        config=TrendScanConfig(
            topics=("baking", "woodworking", "yoga"),
            topics_per_pass=3,
            geo="US",
            allow_rotation_fallback=True,
        ),
        discovery_config=DiscoveryConfig(
            max_depth=3, breadth_depth_0=15, breadth_per_branch=10, recheck_days=90,
            max_evidence_texts=40, max_text_chars=300, exclusions={},
        ),
    )
    seeds, stats = await scanner.scan()
    assert [s.topic for s in seeds] == ["woodworking", "baking", "yoga"]
    assert [s.reason for s in seeds] == ["trends_momentum", "trends_momentum", "rotation"]
    assert stats.scored == 2
    assert fake.chart_calls() == 2, "three topics, one chart pull"


# ── The API key never reaches a log line ─────────────────────────────


def _error_with_key_in_url(status: int, reason: str) -> HttpError:
    """What the real client raises: str() includes the request URI."""
    resp = MagicMock()
    resp.status = status
    resp.reason = "Bad Request"
    content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode("utf-8")
    uri = (
        "https://youtube.googleapis.com/youtube/v3/videoCategories"
        "?part=snippet&regionCode=US&key=SECRET-KEY-123&alt=json"
    )
    return HttpError(resp, content, uri=uri)


def test_the_raw_client_error_really_does_embed_the_key():
    """Guard the premise: if this stops being true the redaction is moot,
    but if it is true and redaction regresses, keys go to the logs."""
    assert "SECRET-KEY-123" in str(_error_with_key_in_url(400, "keyInvalid"))


async def test_a_load_failure_never_carries_the_api_key(caplog):
    import logging

    fake = FakeYouTube(CATS, {}, categories_error=_error_with_key_in_url(400, "keyInvalid"))
    a = _adapter(fake)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(TrendChartUnavailableError) as first:
            await a.fetch_trend("woodworking")
        with pytest.raises(TrendChartUnavailableError) as cached:
            await a.fetch_trend("baking")
    for exc in (first.value, cached.value):
        assert "SECRET-KEY-123" not in str(exc)
        assert "keyInvalid" in str(exc)
        # No original reachable: a chained HttpError would put the URL, and
        # the key, back into any traceback that logs this.
        assert exc.__cause__ is None
        assert exc.__context__ is None or exc.__suppress_context__
    assert "SECRET-KEY-123" not in caplog.text


async def test_a_skipped_category_does_not_log_the_key(caplog):
    import logging

    fake = FakeYouTube(CATS, {
        "26": _error_with_key_in_url(404, "videoChartNotFound"),
        "2": [],
    })
    with caplog.at_level(logging.DEBUG, logger="corp.workers.adapters.youtube_trends"):
        await _adapter(fake).fetch_trend("anything")
    assert "videoChartNotFound" in caplog.text
    assert "SECRET-KEY-123" not in caplog.text


def test_redaction_helpers():
    from corp.workers.adapters.youtube import describe_http_error, redact_api_key

    assert redact_api_key("GET https://x/y?a=1&key=ABC&alt=json") == (
        "GET https://x/y?a=1&key=REDACTED&alt=json"
    )
    assert redact_api_key("https://x/y?key=ABC") == "https://x/y?key=REDACTED"
    assert redact_api_key("no key here") == "no key here"
    msg = describe_http_error(_error_with_key_in_url(403, "quotaExceeded"))
    assert msg == "HttpError 403 (quotaExceeded)"
    assert "SECRET" not in describe_http_error(RuntimeError("see ?key=SECRET-9"))
