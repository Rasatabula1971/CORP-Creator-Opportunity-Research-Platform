"""Kickstarter and Indiegogo adapter — crowdfunding backing as the
strongest commercial-intent signal (CORP1 Stage 5, T13 / Phase 2.3).

Someone backing a crowdfunding project has already paid real money for
something that doesn't exist yet — "the most powerful demand signal
available" (Stage 3, "Why it matters"). Both platforms are queried via
their own public, unauthenticated search endpoints, verified live
(navigated to the real sites and inspected real network traffic) before
writing this module, not assumed from a similar adapter's pattern —
see docs/DECISIONS for T11/T12, where an unverified guess had to be
thrown away.

**Kickstarter**: ``GET /discover/advanced.json?term=<query>&sort=magic
&state[]=successful&state[]=failed&state[]=live`` — confirmed live,
returns project name/blurb/goal/pledged/backers_count/category/state/
percent_funded/dates directly, no auth needed. Comments/community-
engagement counts are NOT in this response: Kickstarter's discussion
data lives behind its GraphQL API, which needs reverse-engineered
persisted-query hashes — out of scope here, flagged rather than
silently dropped (see "What it collects" gap below).

**Indiegogo**: ``POST /api/projectSearch/searchProjects`` with JSON
body ``{"term": <query>, "pageIndex": 0, "pageSize": <n>}`` — confirmed
live by testing several parameter-name guesses against the real
endpoint (``query``/``q``/``keywords``/``searchTerm``/``searchQuery``/
``text`` all silently returned unfiltered global results instead of
erroring; only ``term`` actually filters). Returns project name/
shortDescription/catalogCategory (numeric)/campaignOutcome (numeric)/
dates/url — but NOT funding amount or backer count, which Indiegogo
only server-renders into each individual project's HTML page (verified:
"147 backers raised" appears in a live project page's text, not in this
list endpoint's JSON). Fetching those would need one extra page request
per project (a bounded N+1, same shape as AmazonReviewAdapter's
product -> reviews pattern) — deferred rather than built now, to keep
this first version simple and bounded to one call per platform per
query. ``catalogCategory``/``campaignOutcome`` are stored as raw
numeric values, not translated to a label: the samples checked weren't
enough to confidently confirm what each value means.

Both platforms' data becomes ``source_platform="crowdfunding"`` content,
with ``metadata["platform"]`` distinguishing "kickstarter"/"indiegogo" —
the same umbrella-platform convention ``MarketplaceAdapter`` already
uses for gumroad/etsy/udemy.

ComplianceStatus is VERIFY: both are undocumented internal endpoints
(not a published public API), same status MarketplaceAdapter assigns
its own scraped marketplace listings.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
)

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import (
    AdapterFamily,
    NormalizedContent,
    SourceAdapter,
    check_response_size,
    wait_with_retry_after,
)
from corp.workers.adapters.ids import stable_id
from corp.workers.providers.capabilities import TransactionProvider

logger = logging.getLogger(__name__)

KICKSTARTER_DISCOVER_URL = "https://www.kickstarter.com/discover/advanced.json"
INDIEGOGO_SEARCH_URL = "https://www.indiegogo.com/api/projectSearch/searchProjects"

PLATFORMS: tuple[str, ...] = ("kickstarter", "indiegogo")


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503)
    return isinstance(exc, httpx.TransportError)


class CrowdfundingAdapter(SourceAdapter, TransactionProvider):
    """Collects crowdfunding projects from Kickstarter and Indiegogo as
    purchase-intent signals.

    Each project becomes a ``project`` content item. Kickstarter items
    carry funding/backer/state metadata directly; Indiegogo items carry
    description/category/outcome metadata (funding/backer figures are a
    documented gap, see module docstring).
    """

    def __init__(
        self,
        max_projects: int = 30,
        platforms: list[str] | None = None,
        request_interval_seconds: float = 2.0,
        client: httpx.AsyncClient | None = None,
        proxy: str | None = None,
    ) -> None:
        self._proxy = proxy or None
        self._max_projects = max_projects
        self._platforms = platforms or list(PLATFORMS)
        self._interval = request_interval_seconds
        self._client = client
        self._last_request_at: float | None = None
        self.request_count = 0

    @property
    def platform(self) -> str:
        return "crowdfunding"

    @property
    def family(self) -> AdapterFamily:
        return AdapterFamily.NICHE

    @property
    def access_method(self) -> AccessMethod:
        return AccessMethod.OPEN

    @property
    def compliance_status(self) -> ComplianceStatus:
        return ComplianceStatus.VERIFY

    async def collect(self, identifier: str) -> list[NormalizedContent]:
        identifier = identifier.strip()
        for platform in PLATFORMS:
            prefix = f"{platform}:"
            if identifier.startswith(prefix):
                return await self._collect_from(platform, identifier[len(prefix):].strip())
        return await self._collect_all(identifier)

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def fetch_transactions(self, query: str) -> list[NormalizedContent]:
        """TransactionProvider (CORP1 Stage 5, T13): delegates to
        collect() unchanged."""
        return await self.collect(query)

    async def _collect_all(self, query: str) -> list[NormalizedContent]:
        results: list[NormalizedContent] = []
        per_platform = max(1, self._max_projects // len(self._platforms))
        errors: list[tuple[str, Exception]] = []
        attempted = 0
        for platform in self._platforms:
            if len(results) >= self._max_projects:
                break
            attempted += 1
            try:
                items = await self._collect_from(platform, query, limit=per_platform)
            except Exception as exc:
                # Isolate platforms: one failing site must not discard
                # projects already gathered from the other.
                logger.warning("Crowdfunding platform %s failed for %r: %s", platform, query, exc)
                errors.append((platform, exc))
                continue
            for item in items:
                if len(results) >= self._max_projects:
                    break
                results.append(item)
        if errors and len(errors) == attempted and not results:
            summary = "; ".join(f"{p}: {e}" for p, e in errors)
            raise RuntimeError(f"All crowdfunding platforms failed for {query!r}: {summary}")
        return results

    async def _collect_from(
        self, platform: str, query: str, limit: int | None = None
    ) -> list[NormalizedContent]:
        limit = limit or self._max_projects
        if platform == "kickstarter":
            return await self._collect_kickstarter(query, limit)
        if platform == "indiegogo":
            return await self._collect_indiegogo(query, limit)
        logger.warning("Unknown crowdfunding platform: %s", platform)
        return []

    async def _collect_kickstarter(self, query: str, limit: int) -> list[NormalizedContent]:
        data = await self._get_json(
            KICKSTARTER_DISCOVER_URL,
            params={
                "term": query,
                "sort": "magic",
                "state[]": ["successful", "failed", "live"],
            },
        )
        return _parse_kickstarter_response(data, query)[:limit]

    async def _collect_indiegogo(self, query: str, limit: int) -> list[NormalizedContent]:
        data = await self._post_json(
            INDIEGOGO_SEARCH_URL,
            json_body={"term": query, "pageIndex": 0, "pageSize": min(max(limit, 1), 60)},
        )
        return _parse_indiegogo_response(data, query)[:limit]

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                proxy=self._proxy,
                headers={"Accept": "application/json"},
                timeout=20.0,
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
        wait=wait_with_retry_after(multiplier=2, minimum=2, maximum=30),
        reraise=True,
    )
    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        await self._throttle()
        client = self._get_client()
        resp = await client.get(url, params=params)
        self.request_count += 1
        resp.raise_for_status()
        check_response_size(resp, "crowdfunding")
        return resp.json()  # type: ignore[no-any-return]

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_with_retry_after(multiplier=2, minimum=2, maximum=30),
        reraise=True,
    )
    async def _post_json(self, url: str, json_body: dict[str, Any]) -> dict[str, Any]:
        await self._throttle()
        client = self._get_client()
        resp = await client.post(url, json=json_body)
        self.request_count += 1
        resp.raise_for_status()
        check_response_size(resp, "crowdfunding")
        return resp.json()  # type: ignore[no-any-return]


def _parse_kickstarter_response(data: dict[str, Any], query: str) -> list[NormalizedContent]:
    results: list[NormalizedContent] = []
    now = datetime.now(tz=UTC)

    for project in data.get("projects", []):
        name = str(project.get("name") or "")
        blurb = str(project.get("blurb") or "")
        text = f"{name}\n\n{blurb}".strip() if blurb else name
        if not text:
            continue

        category = project.get("category")
        category_name = category.get("name") if isinstance(category, dict) else None
        creator = project.get("creator")
        creator_name = creator.get("name") if isinstance(creator, dict) else None
        urls = project.get("urls")
        web = urls.get("web") if isinstance(urls, dict) else None
        project_url = web.get("project") if isinstance(web, dict) else None

        launched_at = project.get("launched_at")
        timestamp = (
            datetime.fromtimestamp(launched_at, tz=UTC)
            if isinstance(launched_at, (int, float))
            else now
        )

        results.append(
            NormalizedContent(
                source_platform="crowdfunding",
                content_type="project",
                external_id=stable_id("ks_", str(project.get("id"))),
                text=text,
                author=creator_name,
                timestamp=timestamp,
                url=project_url,
                access_method=AccessMethod.OPEN,
                compliance_status=ComplianceStatus.VERIFY,
                metadata={
                    "platform": "kickstarter",
                    "query": query,
                    "state": project.get("state"),
                    "goal": project.get("goal"),
                    "pledged": project.get("pledged"),
                    "backers_count": project.get("backers_count"),
                    "percent_funded": project.get("percent_funded"),
                    "currency": project.get("currency"),
                    "category": category_name,
                },
            )
        )
    return results


def _parse_indiegogo_response(data: dict[str, Any], query: str) -> list[NormalizedContent]:
    results: list[NormalizedContent] = []
    now = datetime.now(tz=UTC)

    for project in data.get("pagedItems", []):
        name = str(project.get("name") or "")
        short_description = str(project.get("shortDescription") or "")
        text = f"{name}\n\n{short_description}".strip() if short_description else name
        if not text:
            continue

        timestamp = _parse_indiegogo_date(project.get("publishedDate")) or now

        results.append(
            NormalizedContent(
                source_platform="crowdfunding",
                content_type="project",
                external_id=stable_id("ig_", str(project.get("projectID"))),
                text=text,
                author=project.get("creatorName"),
                timestamp=timestamp,
                url=project.get("projectPageUrl"),
                access_method=AccessMethod.OPEN,
                compliance_status=ComplianceStatus.VERIFY,
                metadata={
                    "platform": "indiegogo",
                    "query": query,
                    # Raw values only -- catalogCategory/campaignOutcome
                    # are numeric enums whose exact mapping wasn't
                    # confidently confirmed against the live site; not
                    # translated to a label to avoid asserting an
                    # unverified meaning (see module docstring).
                    "catalog_category_id": project.get("catalogCategory"),
                    "campaign_outcome_raw": project.get("campaignOutcome"),
                    "campaign_goal": project.get("campaignGoal"),
                },
            )
        )
    return results


def _parse_indiegogo_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
