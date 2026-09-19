"""Google Trends adapter — RSS feed + optional pytrends-modern.

Two signal modes:

1. **Trending Now RSS** (licensed, compliant) — Google's own public feed
   at ``trends.google.com/trending/rss``. Returns currently trending
   topics for a given geo. No key required.

2. **Interest-over-time** (tolerated) — uses ``pytrends-modern`` when
   installed to fetch historical search interest for a keyword. This
   wraps an undocumented Google endpoint; widely used commercially
   but not officially supported. Adapter logs a warning on use.

Identifier forms accepted by :meth:`collect`:

* ``trending:US`` — trending topics in the US (or any geo code).
* ``trending`` — defaults to US.
* bare ``keyword`` — interest-over-time via pytrends (if installed),
  otherwise falls back to trending topics matching the keyword.

ComplianceStatus is COMPLIANT for the RSS feed, VERIFY for pytrends data.
"""

import asyncio
import logging
from datetime import UTC, datetime
from xml.etree import ElementTree

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import AdapterFamily, NormalizedContent, SourceAdapter, stable_id

logger = logging.getLogger(__name__)

TRENDS_RSS_URL = "https://trends.google.com/trending/rss"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503)
    return isinstance(exc, httpx.TransportError)


def _has_pytrends() -> bool:
    try:
        import pytrends  # noqa: F401
        return True
    except ImportError:
        return False


class GoogleTrendsAdapter(SourceAdapter):
    """Collects trending topics and search interest data from Google Trends.

    Trending topics from the RSS feed become ``trend`` items. Interest-
    over-time data (when pytrends is available) becomes ``interest``
    items with time-series data in metadata.
    """

    def __init__(
        self,
        max_items: int = 50,
        geo: str = "US",
        request_interval_seconds: float = 2.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._max_items = max_items
        self._geo = geo
        self._interval = request_interval_seconds
        self._client = client
        self._last_request_at: float | None = None
        self.request_count = 0

    @property
    def platform(self) -> str:
        return "googletrends"

    @property
    def family(self) -> AdapterFamily:
        return AdapterFamily.NICHE

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.COMPLIANT

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        identifier = identifier.strip()
        if identifier.startswith("trending:"):
            geo = identifier[9:].strip().upper() or self._geo
            return await self._collect_trending(geo)
        if identifier == "trending":
            return await self._collect_trending(self._geo)
        return await self._collect_interest(identifier)

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _collect_trending(self, geo: str) -> list[NormalizedContent]:
        xml_text = await self._get_page(
            TRENDS_RSS_URL, params={"geo": geo}
        )
        return _parse_trends_rss(xml_text, geo)[: self._max_items]

    async def _collect_interest(self, keyword: str) -> list[NormalizedContent]:
        if not _has_pytrends():
            # No pytrends → no keyword-specific interest series. Fall back to the
            # trending feed but keep only topics that actually mention the
            # keyword; returning the whole geo's unrelated trending list would
            # tag ~50 irrelevant items as evidence for this query.
            logger.info(
                "pytrends not installed; returning keyword-matched trending topics for %r",
                keyword,
            )
            trending = await self._collect_trending(self._geo)
            needle = keyword.casefold()
            matched = [item for item in trending if needle in item.text.casefold()]
            if not matched:
                logger.info("No trending topics matched %r; no interest data", keyword)
            return matched

        logger.info(
            "Using pytrends (tolerated/undocumented endpoint) for %r", keyword
        )
        return await self._fetch_interest_over_time(keyword)

    async def _fetch_interest_over_time(
        self, keyword: str
    ) -> list[NormalizedContent]:
        try:
            from pytrends.request import TrendReq

            loop = asyncio.get_running_loop()
            pytrends = TrendReq(hl="en-US", tz=360)

            def _build():
                pytrends.build_payload([keyword], timeframe="today 3-m", geo=self._geo)
                return pytrends.interest_over_time()

            df = await loop.run_in_executor(None, _build)

            if df is None or df.empty:
                return []

            data_points = []
            for ts, row in df.iterrows():
                data_points.append({
                    "date": str(ts.date()),
                    "interest": int(row.get(keyword, 0)),
                })

            avg_interest = sum(d["interest"] for d in data_points) / max(len(data_points), 1)

            return [
                NormalizedContent(
                    source_platform="googletrends",
                    content_type="interest",
                    external_id=stable_id("gt_iot", keyword, self._geo),
                    text=f"Google Trends interest-over-time for '{keyword}' ({self._geo})",
                    author=None,
                    timestamp=datetime.now(tz=UTC),
                    url=f"https://trends.google.com/trends/explore?q={keyword}&geo={self._geo}",
                    access_method=AccessMethod.OPEN,
                    compliance_status=ComplianceStatus.VERIFY,
                    metadata={
                        "keyword": keyword,
                        "geo": self._geo,
                        "timeframe": "today 3-m",
                        "avg_interest": round(avg_interest, 1),
                        "data_points": data_points[-14:],
                        "total_points": len(data_points),
                    },
                )
            ]
        except Exception as exc:
            logger.warning("pytrends failed for %r: %s", keyword, exc)
            return []

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
            )
        return self._client

    async def _throttle(self) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        if self._last_request_at is not None:
            wait = self._interval - (now - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
        self._last_request_at = loop.time()

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def _get_page(
        self, url: str, params: dict[str, str] | None = None
    ) -> str:
        await self._throttle()
        client = self._get_client()
        resp = await client.get(url, params=params)
        self.request_count += 1
        resp.raise_for_status()
        return resp.text


def _parse_trends_rss(xml_text: str, geo: str) -> list[NormalizedContent]:
    results: list[NormalizedContent] = []
    now = datetime.now(tz=UTC)

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        logger.warning("Failed to parse Google Trends RSS")
        return []

    ns = {"ht": "https://trends.google.com/trending/rss"}

    for item in root.iter("item"):
        title_el = item.find("title")
        title = title_el.text if title_el is not None and title_el.text else ""
        if not title:
            continue

        link_el = item.find("link")
        link = link_el.text if link_el is not None and link_el.text else None

        traffic_el = item.find("ht:approx_traffic", ns)
        traffic = traffic_el.text if traffic_el is not None else None

        pub_date_el = item.find("pubDate")
        timestamp = _parse_rss_date(pub_date_el.text) if pub_date_el is not None and pub_date_el.text else now

        news_items = []
        for ni in item.findall("ht:news_item", ns):
            ni_title = ni.find("ht:news_item_title", ns)
            ni_url = ni.find("ht:news_item_url", ns)
            if ni_title is not None and ni_title.text:
                news_items.append({
                    "title": ni_title.text,
                    "url": ni_url.text if ni_url is not None else None,
                })

        ext_id = stable_id("gt", title, geo)

        results.append(
            NormalizedContent(
                source_platform="googletrends",
                content_type="trend",
                external_id=ext_id,
                text=title,
                author=None,
                timestamp=timestamp,
                url=link,
                access_method=AccessMethod.OPEN,
                compliance_status=ComplianceStatus.COMPLIANT,
                metadata={
                    "geo": geo,
                    "approx_traffic": traffic,
                    "news_items": news_items[:5],
                },
            )
        )

    return results


def _parse_rss_date(text: str) -> datetime | None:
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(text)
    except Exception:
        return None
    # RSS pubDate carries an offset (e.g. -0700). .replace(tzinfo=UTC) would keep
    # the wall-clock and relabel the zone, shifting the instant by that offset;
    # astimezone converts correctly. A rare offset-less date is treated as UTC.
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
