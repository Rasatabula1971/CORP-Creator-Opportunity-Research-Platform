"""Creator-web adapter — the creator's own public pages.

Linktree-style hubs, shops, course pages, media kits and sponsor disclosures
tell CORP what a creator already sells and who already pays them. That is
the competition-saturation signal the scoring engine is missing.

v1 fetches static HTML with httpx and the standard-library parser. Pages that
need JavaScript rendering come back mostly empty; crawl4ai is the planned
upgrade for those. Access is ``open`` / ``compliant``: these are pages the
creator published to be read.
"""

import asyncio
import ipaddress
import logging
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import AdapterFamily, NormalizedContent, SourceAdapter

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "corp-research/0.1 (creator opportunity research)"

# Identifiers and outbound links come from API callers and creator pages, so
# every hop is checked against public address space before it is fetched.
MAX_REDIRECTS = 5
# Bytes of a page body read before giving up; keeps a huge page from being
# buffered whole just to keep ``max_text_chars`` of it.
MAX_BODY_BYTES = 2_000_000

# Outbound links whose host or path suggests monetisation or partnership.
COMMERCE_PATTERNS: dict[str, re.Pattern[str]] = {
    "shop": re.compile(r"shop|store|merch|etsy\.|shopify|teespring|spring\.", re.I),
    "course": re.compile(r"course|academy|teachable|thinkific|kajabi|udemy|skillshare", re.I),
    "membership": re.compile(r"patreon|ko-fi|buymeacoffee|memberful|substack|onlyfans", re.I),
    "product": re.compile(r"gumroad|lemonsqueezy|amazon\.[a-z.]+/(shop|stores)|amzn\.to", re.I),
    "sponsor": re.compile(r"sponsor|partner|affiliate|brand|media[-_ ]?kit|collab", re.I),
    "booking": re.compile(r"calendly|cal\.com|book|consult|coaching", re.I),
}

_SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}


class _TextAndLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.links: list[tuple[str, str]] = []
        self._text: list[str] = []
        self._skip = 0
        self._in_title = False
        self._current_href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta" and (a.get("name") or a.get("property") or "").lower() in (
            "description",
            "og:description",
        ):
            self.description = self.description or (a.get("content") or "").strip()
        elif tag == "a" and a.get("href"):
            self._current_href = a["href"]
            self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._current_href is not None:
            self.links.append((self._current_href, " ".join(self._anchor_text).strip()))
            self._current_href = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        chunk = data.strip()
        if not chunk:
            return
        if self._in_title:
            self.title += chunk
            return
        if self._current_href is not None:
            self._anchor_text.append(chunk)
        self._text.append(chunk)

    @property
    def text(self) -> str:
        return "\n".join(self._text)


def parse_page(html: str, base_url: str) -> dict[str, Any]:
    """Extract title, description, visible text, and classified outbound links."""
    parser = _TextAndLinks()
    parser.feed(html)
    links = []
    for href, label in parser.links:
        absolute = urljoin(base_url, href)
        if not absolute.startswith(("http://", "https://")):
            continue
        kinds = [
            k for k, pat in COMMERCE_PATTERNS.items() if pat.search(absolute) or pat.search(label)
        ]
        links.append({"url": absolute, "label": label[:200], "kinds": kinds})
    return {
        "title": parser.title.strip(),
        "description": parser.description,
        "text": parser.text,
        "links": links,
        "commerce_signals": sorted({k for link in links for k in link["kinds"]}),
    }


class WebPresenceAdapter(SourceAdapter):
    """Collects a creator's landing page and its commerce-related outbound pages."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        max_pages: int = 8,
        request_interval_seconds: float = 1.0,
        max_text_chars: int = 20_000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._max_pages = max_pages
        self._interval = request_interval_seconds
        self._max_text = max_text_chars
        self._client = client

    @property
    def platform(self) -> str:
        return "web"

    @property
    def family(self) -> AdapterFamily:
        return AdapterFamily.CREATOR_WEB

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.COMPLIANT

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        start = identifier.strip()
        if not start.startswith(("http://", "https://")):
            start = f"https://{start}"
        if not urlparse(start).path:
            start += "/"
        results: list[NormalizedContent] = []
        seen: set[str] = set()

        landing = await self._fetch_page(start)
        if landing is None:
            return results
        results.append(landing)
        # seen holds normalized URL keys. Track both the requested start and the
        # (possibly redirected) landing external_id so a candidate pointing at
        # either is skipped.
        seen.add(_normalize(start))
        seen.add(landing.external_id)

        # Follow only links that look commercial; those are the ones that matter.
        candidates = [
            link["url"] for link in landing.metadata["links"] if link["kinds"]
        ]
        for url in candidates:
            if len(results) >= self._max_pages:
                break
            key = _normalize(url)
            if key in seen:
                continue
            # Mark before fetching so a repeated or dead candidate isn't retried.
            seen.add(key)
            await asyncio.sleep(self._interval)
            page = await self._fetch_page(url)
            if page is None:
                continue
            # A redirect can land on a different, already-collected page; skip
            # that. (When there's no redirect external_id == key, which we just
            # added, so guard on the difference to avoid skipping every page.)
            if page.external_id != key and page.external_id in seen:
                continue
            results.append(page)
            seen.add(page.external_id)
        return results

    async def _fetch_page(self, url: str) -> NormalizedContent | None:
        fetched = await self._fetch_html(url)
        if fetched is None:
            return None
        final_url, html = fetched
        parsed = parse_page(html, final_url)
        text = parsed["text"][: self._max_text]
        return NormalizedContent(
            source_platform="web",
            content_type="page",
            external_id=_normalize(final_url),
            text=text,
            url=final_url[:500],
            access_method=self.access_method,
            compliance_status=self.compliance_status,
            metadata={
                "title": parsed["title"],
                "description": parsed["description"],
                "domain": urlparse(final_url).netloc,
                "links": parsed["links"][:100],
                "commerce_signals": parsed["commerce_signals"],
            },
        )

    async def _fetch_html(self, url: str) -> tuple[str, str] | None:
        """GET ``url`` following redirects by hand so each hop is host-checked.

        Returns ``(final_url, html)`` or None for non-public hosts, non-HTML
        responses, HTTP errors and redirect loops.
        """
        client = self._get_client()
        try:
            for _ in range(MAX_REDIRECTS + 1):
                if not await is_public_url(url):
                    logger.warning("Refusing to fetch non-public URL %s", url)
                    return None
                async with client.stream("GET", url, follow_redirects=False) as resp:
                    if resp.next_request is not None:
                        url = str(resp.next_request.url)
                        continue
                    resp.raise_for_status()
                    if "html" not in resp.headers.get("content-type", "").lower():
                        return None
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) >= MAX_BODY_BYTES:
                            logger.warning(
                                "Body of %s exceeds %d bytes; truncated", url, MAX_BODY_BYTES
                            )
                            del buf[MAX_BODY_BYTES:]
                            break
                    return url, bytes(buf).decode(resp.encoding or "utf-8", errors="replace")
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            logger.warning("Fetch failed for %s: %s", url, exc)
            return None
        logger.warning("Too many redirects fetching %s", url)
        return None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": self._user_agent},
                timeout=20.0,
            )
        return self._client


async def _resolve_host(host: str) -> list[str]:
    """All addresses ``host`` resolves to. Module-level so tests can stub it."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def is_public_url(url: str) -> bool:
    """True only for http(s) URLs whose host resolves solely to public addresses.

    Blocks loopback, private, link-local (cloud metadata) and reserved ranges
    so an API-supplied identifier or a creator-page link can't point the worker
    at internal services.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme not in ("http", "https") or not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        addrs = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addrs = await _resolve_host(host)
        except (socket.gaierror, OSError) as exc:
            logger.warning("Cannot resolve %s: %s", host, exc)
            return False
    if not addrs:
        return False
    for addr in addrs:
        try:
            ip = ipaddress.ip_address(addr.split("%", 1)[0])
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def _normalize(url: str) -> str:
    """Stable id for a page: scheme+host+path, no query/fragment, max 255 chars."""
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return f"{p.scheme}://{p.netloc.lower()}{path}"[:255]
