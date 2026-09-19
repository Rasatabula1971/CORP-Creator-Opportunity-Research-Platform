"""Unit tests for the creator-web adapter — HTTP mocked, no network."""

import httpx

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import AdapterFamily
from corp.workers.adapters.web import WebPresenceAdapter, parse_page

LANDING = """
<html><head><title>Maker Hub</title>
<meta name="description" content="Links and stuff">
<style>.x{}</style><script>var a=1;</script></head>
<body>
<h1>Welcome</h1>
<p>I make woodworking videos.</p>
<a href="/shop">My Shop</a>
<a href="https://patreon.com/maker">Support on Patreon</a>
<a href="https://example.com/about">About me</a>
<a href="mailto:me@example.com">Email</a>
<a href="https://teachable.com/maker/course">Desk building course</a>
</body></html>
"""
SHOP = "<html><head><title>Shop</title></head><body><p>Bracket kit $29</p></body></html>"


async def _resolve_public(host: str) -> list[str]:
    """Test double: every host resolves to a fixed public IP, no real DNS."""
    return ["93.184.216.34"]


def _adapter(routes: dict[str, httpx.Response], calls=None, **kw) -> WebPresenceAdapter:
    async def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        return routes.get(str(request.url), httpx.Response(404, text="nope"))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    kw.setdefault("resolve_host", _resolve_public)
    return WebPresenceAdapter(request_interval_seconds=0.0, client=client, **kw)


def _html(body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})


def test_parse_page_extracts_text_links_and_commerce_signals():
    parsed = parse_page(LANDING, "https://example.com/")
    assert parsed["title"] == "Maker Hub"
    assert parsed["description"] == "Links and stuff"
    assert "I make woodworking videos." in parsed["text"]
    assert "var a=1" not in parsed["text"]
    urls = {link["url"]: link for link in parsed["links"]}
    assert "https://example.com/shop" in urls  # relative resolved
    assert "mailto:me@example.com" not in urls  # non-http dropped
    assert "shop" in urls["https://example.com/shop"]["kinds"]
    assert "membership" in urls["https://patreon.com/maker"]["kinds"]
    assert "course" in urls["https://teachable.com/maker/course"]["kinds"]
    assert urls["https://example.com/about"]["kinds"] == []
    assert parsed["commerce_signals"] == ["course", "membership", "shop"]


def test_contract():
    a = WebPresenceAdapter(request_interval_seconds=0.0)
    assert a.platform == "web"
    assert a.family == AdapterFamily.CREATOR_WEB
    assert a.access_method == AccessMethod.OPEN
    assert a.compliance_status == ComplianceStatus.COMPLIANT


async def test_collect_landing_then_only_commercial_links():
    calls: list[str] = []
    routes = {
        "https://example.com/": _html(LANDING),
        "https://example.com/shop": _html(SHOP),
        "https://patreon.com/maker": httpx.Response(403, text="blocked"),
        "https://teachable.com/maker/course": httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        ),
    }
    a = _adapter(routes, calls)
    items = await a.collect("example.com")

    assert [i.external_id for i in items] == ["https://example.com/", "https://example.com/shop"]
    landing, shop = items
    assert landing.content_type == "page"
    assert landing.metadata["title"] == "Maker Hub"
    assert landing.metadata["domain"] == "example.com"
    assert landing.metadata["commerce_signals"] == ["course", "membership", "shop"]
    assert "Bracket kit $29" in shop.text
    # About page (no commerce kind) was never fetched; mailto never fetched.
    assert "https://example.com/about" not in calls
    assert len(calls) == 4
    await a.close()


async def test_max_pages_and_dedupe():
    routes = {
        "https://example.com/": _html(LANDING),
        "https://example.com/shop": _html(SHOP),
    }
    a = _adapter(routes, max_pages=1)
    items = await a.collect("https://example.com/")
    assert len(items) == 1
    await a.close()


async def test_unreachable_landing_returns_empty():
    a = _adapter({})
    assert await a.collect("https://nowhere.example/") == []
    await a.close()


async def test_dedupes_links_that_normalize_equal():
    landing = (
        "<html><head><title>Hub</title></head><body>"
        '<a href="/shop">Shop</a><a href="/shop?ref=aff">Shop aff</a>'
        "</body></html>"
    )
    calls: list[str] = []
    routes = {
        "https://example.com/": _html(landing),
        "https://example.com/shop": _html(SHOP),
        "https://example.com/shop?ref=aff": _html(SHOP),
    }
    a = _adapter(routes, calls=calls, max_pages=10)
    items = await a.collect("https://example.com/")
    # Both links normalize to the same key → landing + one shop page.
    assert len(items) == 2
    assert len([u for u in calls if "/shop" in u]) == 1
    await a.close()


async def test_no_duplicate_when_candidates_redirect_to_same_page():
    landing = (
        "<html><head><title>Hub</title></head><body>"
        '<a href="/store">Store</a><a href="/merch">Merch</a>'
        "</body></html>"
    )
    routes = {
        "https://example.com/": _html(landing),
        "https://example.com/store": httpx.Response(
            302, headers={"location": "https://example.com/shop"}
        ),
        "https://example.com/merch": httpx.Response(
            302, headers={"location": "https://example.com/shop"}
        ),
        "https://example.com/shop": _html(SHOP),
    }
    a = _adapter(routes, max_pages=10)
    items = await a.collect("https://example.com/")
    shop_pages = [i for i in items if i.external_id == "https://example.com/shop"]
    assert len(shop_pages) == 1  # both redirects land on /shop; collected once
    await a.close()


async def test_refuses_host_resolving_to_private_ip():
    async def resolve_private(host: str) -> list[str]:
        return ["10.0.0.5"]

    a = _adapter({"https://internal.example/": _html(LANDING)}, resolve_host=resolve_private)
    assert await a.collect("internal.example") == []
    await a.close()


async def test_refuses_literal_ip_in_reserved_range():
    calls: list[str] = []
    a = _adapter({}, calls=calls)
    assert await a.collect("http://169.254.169.254/latest/meta-data/") == []
    assert calls == []  # never even attempted the request
    await a.close()


async def test_refuses_redirect_into_private_ip():
    routes = {
        "https://example.com/": httpx.Response(
            302, headers={"location": "http://internal.example/secret"}
        ),
    }

    async def resolve(host: str) -> list[str]:
        return ["10.0.0.5"] if host == "internal.example" else ["93.184.216.34"]

    a = _adapter(routes, resolve_host=resolve)
    assert await a.collect("https://example.com/") == []
    await a.close()
