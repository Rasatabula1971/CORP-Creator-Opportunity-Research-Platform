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
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import AdapterFamily, NormalizedContent, SourceAdapter

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "corp-research/0.1 (creator opportunity research)"

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


def parse_page(html: str, base_url: str) -> dict:
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
            await asyncio.sleep(self._interval)
            page = await self._fetch_page(url)
            if page is not None:
                results.append(page)
                seen.add(page.external_id)
        return results

    async def _fetch_page(self, url: str) -> NormalizedContent | None:
        client = self._get_client()
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            logger.warning("Fetch failed for %s: %s", url, exc)
            return None
        if "html" not in resp.headers.get("content-type", "").lower():
            return None

        final_url = str(resp.url)
        parsed = parse_page(resp.text, final_url)
        text = parsed["text"][: self._max_text]
        return NormalizedContent(
            source_platform="web",
            content_type="page",
            external_id=_normalize(final_url),
            text=text,
            url=final_url,
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

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": self._user_agent},
                timeout=20.0,
                follow_redirects=True,
            )
        return self._client


def _normalize(url: str) -> str:
    """Stable id for a page: scheme+host+path, no query/fragment, max 255 chars."""
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return f"{p.scheme}://{p.netloc.lower()}{path}"[:255]
