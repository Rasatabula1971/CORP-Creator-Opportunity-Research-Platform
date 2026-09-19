"""Unit tests for the Reddit adapter — public JSON endpoints mocked, no network."""

import json
from urllib.parse import parse_qs

import httpx
import pytest

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import SourceAdapter
from corp.workers.adapters.reddit import RedditAdapter


def _listing(posts: list[dict], after: str | None = None) -> dict:
    return {
        "kind": "Listing",
        "data": {"after": after, "children": [{"kind": "t3", "data": p} for p in posts]},
    }


def _post(pid: str, title: str = "Help with X", body: str = "", n_comments: int = 2) -> dict:
    return {
        "id": pid,
        "title": title,
        "selftext": body,
        "author": "creator",
        "created_utc": 1_700_000_000,
        "permalink": f"/r/test/comments/{pid}/help/",
        "subreddit": "test",
        "score": 42,
        "upvote_ratio": 0.9,
        "num_comments": n_comments,
        "link_flair_text": "Question",
        "is_self": True,
    }


def _comment(cid: str, parent: str, body: str, replies: list | None = None, depth: int = 0):
    return {
        "kind": "t1",
        "data": {
            "id": cid,
            "parent_id": parent,
            "body": body,
            "author": f"user_{cid}",
            "created_utc": 1_700_000_100,
            "permalink": f"/r/test/comments/abc/help/{cid}/",
            "score": 3,
            "depth": depth,
            "replies": {"kind": "Listing", "data": {"children": replies}} if replies else "",
        },
    }


def _thread(post: dict, comments: list[dict]) -> list:
    return [
        _listing([post]),
        {"kind": "Listing", "data": {"children": comments}},
    ]


def _adapter(routes: dict[str, object], calls: list | None = None) -> RedditAdapter:
    """Build an adapter whose HTTP client answers from a path→body table."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        body = routes.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"error": 404})
        if isinstance(body, httpx.Response):
            return body
        return httpx.Response(200, json=body)

    client = httpx.AsyncClient(
        base_url="https://www.reddit.com",
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": "test-agent"},
    )
    return RedditAdapter(
        user_agent="test-agent",
        posts_per_creator=25,
        request_interval_seconds=0.0,
        client=client,
    )


def test_implements_source_adapter():
    adapter = RedditAdapter(request_interval_seconds=0.0)
    assert isinstance(adapter, SourceAdapter)
    assert adapter.platform == "reddit"
    assert adapter.access_method == AccessMethod.OPEN
    assert adapter.compliance_status == ComplianceStatus.VERIFY


async def test_implements_problem_and_dissatisfaction_provider(monkeypatch):
    """CORP1 Stage 4/5, T2: Reddit is ProblemProvider + DissatisfactionProvider,
    both delegating to the same collect()."""
    from corp.workers.providers.capabilities import DissatisfactionProvider, ProblemProvider

    adapter = RedditAdapter(request_interval_seconds=0.0)
    assert isinstance(adapter, ProblemProvider)
    assert isinstance(adapter, DissatisfactionProvider)

    sentinel: list[object] = []
    calls: list[str] = []

    async def fake_collect(identifier: str) -> list[object]:
        calls.append(identifier)
        return sentinel

    monkeypatch.setattr(adapter, "collect", fake_collect)

    assert await adapter.fetch_problems("home espresso") is sentinel
    assert await adapter.fetch_dissatisfaction("home espresso") is sentinel
    assert calls == ["home espresso", "home espresso"]


@pytest.mark.parametrize(
    "identifier, path",
    [
        ("r/python", "/r/python/new.json"),
        ("python", "/r/python/new.json"),
        ("/r/python/", "/r/python/new.json"),
        ("u/spez", "/user/spez/submitted.json"),
        ("user/spez", "/user/spez/submitted.json"),
    ],
)
def test_listing_path(identifier, path):
    assert RedditAdapter._listing_path(identifier) == path


async def test_list_posts_maps_fields():
    adapter = _adapter({"/r/test/new.json": _listing([_post("abc", body="details here")])})
    posts = await adapter.list_posts("r/test")
    assert len(posts) == 1
    p = posts[0]
    assert p.content_type == "post"
    assert p.external_id == "abc"
    assert p.text == "Help with X\n\ndetails here"
    assert p.author == "creator"
    assert p.timestamp is not None and p.timestamp.year == 2023
    assert p.url == "https://www.reddit.com/r/test/comments/abc/help/"
    assert p.metadata["like_count"] == 42
    assert p.metadata["comment_count"] == 2
    assert p.metadata["description"] == "details here"
    await adapter.close()


async def test_list_posts_paginates_until_limit():
    calls: list[httpx.Request] = []
    page1 = _listing([_post(f"p{i}") for i in range(3)], after="t3_p2")
    page2 = _listing([_post(f"p{i}") for i in range(3, 6)], after=None)

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        qs = parse_qs(request.url.query.decode())
        return httpx.Response(200, json=page2 if "after" in qs else page1)

    client = httpx.AsyncClient(
        base_url="https://www.reddit.com", transport=httpx.MockTransport(handler)
    )
    adapter = RedditAdapter(posts_per_creator=5, request_interval_seconds=0.0, client=client)
    posts = await adapter.list_posts("r/test")
    assert [p.external_id for p in posts] == ["p0", "p1", "p2", "p3", "p4"]
    assert len(calls) == 2
    assert parse_qs(calls[1].url.query.decode())["after"] == ["t3_p2"]
    await adapter.close()


async def test_list_posts_skips_malformed_post_missing_id():
    """A single malformed record (e.g. a promoted/placeholder child with no
    id) must be skipped, not abort the whole batch with a KeyError."""
    good = _post("abc")
    bad = _post("def")
    del bad["id"]
    adapter = _adapter({"/r/test/new.json": _listing([good, bad])})
    posts = await adapter.list_posts("r/test")
    assert [p.external_id for p in posts] == ["abc"]
    await adapter.close()


async def test_get_comments_walks_tree_and_threads_replies():
    comments = [
        _comment(
            "c1",
            "t3_abc",
            "I struggle with this too",
            replies=[_comment("c2", "t1_c1", "same, wish there was a tool", depth=1)],
        ),
        _comment("c3", "t3_abc", "where can I buy one?"),
        {"kind": "more", "data": {"children": ["c9"]}},
    ]
    adapter = _adapter({"/comments/abc.json": _thread(_post("abc"), comments)})
    out = await adapter.get_comments("abc")
    by_id = {c.external_id: c for c in out}
    assert set(by_id) == {"c1", "c2", "c3"}
    assert by_id["c1"].content_type == "comment" and by_id["c1"].parent_id == "abc"
    assert by_id["c3"].content_type == "comment" and by_id["c3"].parent_id == "abc"
    assert by_id["c2"].content_type == "reply" and by_id["c2"].parent_id == "c1"
    assert by_id["c2"].metadata["depth"] == 1
    assert by_id["c2"].metadata["post_id"] == "abc"
    assert by_id["c1"].author == "user_c1"
    await adapter.close()


async def test_get_comments_skips_malformed_comment_but_keeps_its_replies():
    reply = _comment("c2", "t1_c1", "still recursed into")
    malformed = _comment("c1", "t3_abc", "no id", replies=[reply])
    del malformed["data"]["id"]
    adapter = _adapter({"/comments/abc.json": _thread(_post("abc"), [malformed])})
    out = await adapter.get_comments("abc")
    assert [c.external_id for c in out] == ["c2"]
    await adapter.close()


async def test_collect_returns_posts_then_comments():
    routes = {
        "/r/test/new.json": _listing([_post("abc"), _post("def")]),
        "/comments/abc.json": _thread(_post("abc"), [_comment("c1", "t3_abc", "a")]),
        "/comments/def.json": _thread(_post("def"), [_comment("c2", "t3_def", "b")]),
    }
    calls: list[httpx.Request] = []
    adapter = _adapter(routes, calls)
    items = await adapter.collect("r/test")
    assert [i.content_type for i in items] == ["post", "post", "comment", "comment"]
    assert adapter.request_count == 3
    assert all(r.headers["User-Agent"] == "test-agent" for r in calls)
    await adapter.close()


async def test_throttle_spaces_requests(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("corp.workers.adapters.reddit.asyncio.sleep", fake_sleep)
    routes = {
        "/r/test/new.json": _listing([_post("abc")]),
        "/comments/abc.json": _thread(_post("abc"), []),
    }
    adapter = _adapter(routes)
    adapter._interval = 6.0
    await adapter.collect("r/test")
    # First request never sleeps; the second waits close to the full interval.
    assert len(sleeps) == 1
    assert 5.0 < sleeps[0] <= 6.0


async def test_rate_limit_retries_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={})
        return httpx.Response(200, json=_listing([_post("abc")]))

    client = httpx.AsyncClient(
        base_url="https://www.reddit.com", transport=httpx.MockTransport(handler)
    )
    adapter = RedditAdapter(request_interval_seconds=0.0, client=client)
    # Collapse tenacity's exponential backoff so the test is instant.
    adapter._get_json.retry.wait = lambda *_: 0  # type: ignore[attr-defined]
    posts = await adapter.list_posts("r/test")
    assert attempts["n"] == 2
    assert posts[0].external_id == "abc"
    await adapter.close()


async def test_not_found_raises():
    adapter = _adapter({})
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.list_posts("r/doesnotexist")
    await adapter.close()


def test_normalized_content_serializable():
    adapter = RedditAdapter(request_interval_seconds=0.0)
    content = adapter._post_to_content(_post("abc", body="x"))
    json.dumps(content.model_dump(mode="json"))
