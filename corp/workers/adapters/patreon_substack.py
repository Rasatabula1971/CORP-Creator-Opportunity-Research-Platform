"""Patreon and Substack adapter — creator monetisation signals (CORP1
Stage 5, T14 / Phase 2.4).

"If people already pay creators in a niche for content, that niche has
proven monetisation potential" (Stage 3, "Why it matters"). Following
the standing practice adopted after T11/T12 (verify a real source live
before writing any code against it, never assume a field shape), both
platforms were checked before building this adapter:

**Substack**: ``GET /api/v1/top/search?query=<query>&fromSuggestedSearch
=false`` — confirmed live, fully unauthenticated (other Substack API
calls made by the same page returned 401; this one returns 200 without
a session). Returns search hits of several ``type`` values ("post",
"comment", "profileSearchResults"); each "post" hit carries a nested
``publication`` object with real creator/monetisation data: ``name``,
``hero_text``/``author_bio`` (description), ``freeSubscriberCount``,
``payments_state`` ("enabled"/"disabled"), ``plans`` (when payments are
enabled, a list of real Stripe Plan objects — ``amount`` in cents,
``currency``, ``interval``, ``nickname`` — confirmed by fetching a
paid publication's search results directly and inspecting one), and
``sections`` (named content categories). One publication can appear
under multiple "post" hits for the same query; this module de-
duplicates by publication id before emitting one item per creator page.

**Patreon**: **not implemented in this version.** patreon.com is
blocked by this session's built-in browser's own safety restrictions,
and the fallback (Claude in Chrome, the user's real browser) was not
connected when this task was built. Per the standing practice, this
means Patreon's real public data shape was never verified — so, unlike
T11/T12 (where a guess was made and then had to be thrown away), no
code was written against an assumption here at all.
``PatreonSubstackAdapter._collect_from`` recognizes the ``patreon:``
prefix and ``"patreon"`` in ``PLATFORMS`` (so a caller's request for it
is routed correctly, not silently misrouted), but returns an empty
list with a logged warning rather than fabricated results. A future
task can add real Patreon support once its data can be verified live —
see the ADR for this task.

**Known gap, disclosed rather than guessed around**: Substack's public
search API only exposes ``freeSubscriberCount`` (free subscribers), not
a paid/patron count — that number is private business data Substack
doesn't expose publicly. The presence of enabled paid tiers (and their
pricing) is this adapter's actual monetisation signal; free-subscriber
count is stored as an audience-size proxy only, not a "patron count."
Similarly, no direct aggregate comment/engagement count exists in this
endpoint's response; ``community_enabled``/``has_recommendations`` are
stored as coarse community-activity proxies, not a count.

Both platforms' data becomes ``source_platform="patreon_substack"``
content, with ``metadata["platform"]`` distinguishing the site —
the same umbrella-platform convention ``MarketplaceAdapter``/
``CrowdfundingAdapter`` already use.

ComplianceStatus is VERIFY: Substack's search endpoint is real but
undocumented (not a published public API).
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
    wait_exponential,
)

from corp.core.models.evidence import AccessMethod, ComplianceStatus
from corp.workers.adapters.base import AdapterFamily, NormalizedContent, SourceAdapter
from corp.workers.adapters.ids import stable_id
from corp.workers.providers.capabilities import MonetisationProvider

logger = logging.getLogger(__name__)

SUBSTACK_SEARCH_URL = "https://substack.com/api/v1/top/search"

PLATFORMS: tuple[str, ...] = ("substack", "patreon")


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503)
    return isinstance(exc, httpx.TransportError)


class PatreonSubstackAdapter(SourceAdapter, MonetisationProvider):
    """Collects creator pages with monetisation signals from Substack
    (Patreon deferred, see module docstring).

    Each distinct creator/publication becomes one ``creator_page``
    content item. Metadata carries tier pricing (when enabled),
    free-subscriber count, content sections, and community-activity
    proxies.
    """

    def __init__(
        self,
        max_creators: int = 30,
        platforms: list[str] | None = None,
        request_interval_seconds: float = 2.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._max_creators = max_creators
        self._platforms = platforms or list(PLATFORMS)
        self._interval = request_interval_seconds
        self._client = client
        self._last_request_at: float | None = None
        self.request_count = 0

    @property
    def platform(self) -> str:
        return "patreon_substack"

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

    async def fetch_monetisation(self, query: str) -> list[NormalizedContent]:
        """MonetisationProvider (CORP1 Stage 5, T14): delegates to
        collect() unchanged."""
        return await self.collect(query)

    async def _collect_all(self, query: str) -> list[NormalizedContent]:
        results: list[NormalizedContent] = []
        per_platform = max(1, self._max_creators // len(self._platforms))
        errors: list[tuple[str, Exception]] = []
        attempted = 0
        for platform in self._platforms:
            if len(results) >= self._max_creators:
                break
            attempted += 1
            try:
                items = await self._collect_from(platform, query, limit=per_platform)
            except Exception as exc:
                logger.warning("Platform %s failed for %r: %s", platform, query, exc)
                errors.append((platform, exc))
                continue
            for item in items:
                if len(results) >= self._max_creators:
                    break
                results.append(item)
        if errors and len(errors) == attempted and not results:
            summary = "; ".join(f"{p}: {e}" for p, e in errors)
            raise RuntimeError(f"All platforms failed for {query!r}: {summary}")
        return results

    async def _collect_from(
        self, platform: str, query: str, limit: int | None = None
    ) -> list[NormalizedContent]:
        limit = limit or self._max_creators
        if platform == "substack":
            return await self._collect_substack(query, limit)
        if platform == "patreon":
            logger.warning(
                "Patreon collection requested for %r but not implemented in "
                "this adapter version -- its real public data was never "
                "verified (see module docstring); returning no results.",
                query,
            )
            return []
        logger.warning("Unknown platform: %s", platform)
        return []

    async def _collect_substack(self, query: str, limit: int) -> list[NormalizedContent]:
        data = await self._get_json(
            SUBSTACK_SEARCH_URL,
            params={"query": query, "fromSuggestedSearch": "false"},
        )
        return _parse_substack_response(data, query)[:limit]

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
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
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        await self._throttle()
        client = self._get_client()
        resp = await client.get(url, params=params)
        self.request_count += 1
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]


def _parse_substack_response(data: dict[str, Any], query: str) -> list[NormalizedContent]:
    results: list[NormalizedContent] = []
    seen_publication_ids: set[Any] = set()

    for item in data.get("items", []):
        if item.get("type") != "post":
            continue
        publication = item.get("publication")
        if not isinstance(publication, dict):
            continue

        pub_id = publication.get("id")
        if pub_id is None or pub_id in seen_publication_ids:
            continue
        seen_publication_ids.add(pub_id)

        name = str(publication.get("name") or "")
        description = str(publication.get("hero_text") or publication.get("author_bio") or "")
        text = f"{name}\n\n{description}".strip() if description else name
        if not text:
            continue

        results.append(
            NormalizedContent(
                source_platform="patreon_substack",
                content_type="creator_page",
                external_id=stable_id("ss_", str(pub_id)),
                text=text,
                author=publication.get("author_name"),
                timestamp=(
                    _parse_substack_date(publication.get("created_at")) or datetime.now(tz=UTC)
                ),
                url=_substack_url(publication),
                access_method=AccessMethod.OPEN,
                compliance_status=ComplianceStatus.VERIFY,
                metadata={
                    "platform": "substack",
                    "query": query,
                    "payments_enabled": publication.get("payments_state") == "enabled",
                    "tiers": _extract_tiers(publication),
                    # Free subscribers only -- Substack's public search API
                    # never exposes a paid/patron count (private business
                    # data). Enabled-tier presence/pricing is the real
                    # monetisation signal; this is an audience-size proxy.
                    "free_subscriber_count": publication.get("freeSubscriberCount"),
                    "content_sections": _section_names(publication),
                    "community_enabled": publication.get("community_enabled"),
                    "has_recommendations": publication.get("has_recommendations"),
                },
            )
        )
    return results


def _extract_tiers(publication: dict[str, Any]) -> list[dict[str, Any]]:
    if publication.get("payments_state") != "enabled":
        return []
    plans = publication.get("plans")
    if not isinstance(plans, list):
        return []
    tiers: list[dict[str, Any]] = []
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        tiers.append(
            {
                "amount_cents": plan.get("amount"),
                "currency": plan.get("currency"),
                "interval": plan.get("interval"),
                "nickname": plan.get("nickname"),
            }
        )
    return tiers


def _section_names(publication: dict[str, Any]) -> list[str]:
    sections = publication.get("sections")
    if not isinstance(sections, list):
        return []
    return [s["name"] for s in sections if isinstance(s, dict) and s.get("name")]


def _substack_url(publication: dict[str, Any]) -> str | None:
    custom_domain = publication.get("custom_domain")
    if isinstance(custom_domain, str) and custom_domain:
        return f"https://{custom_domain}"
    subdomain = publication.get("subdomain")
    if isinstance(subdomain, str) and subdomain:
        return f"https://{subdomain}.substack.com"
    return None


def _parse_substack_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
