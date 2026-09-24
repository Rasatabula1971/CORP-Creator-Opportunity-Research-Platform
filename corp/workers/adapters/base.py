import enum
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from corp.core.models.evidence import AccessMethod, ComplianceStatus

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES = 10_000_000  # 10 MB


async def close_quietly(obj: object) -> None:
    """Call ``obj.close()`` if it has one, logging rather than raising on
    failure. Cleanup must never mask (or crash alongside) the outcome of
    the work that just finished — shared so every caller in the api and
    workers layers follows the same rule instead of drifting apart."""
    close = getattr(obj, "close", None)
    if close is not None:
        try:
            await close()
        except Exception:
            logger.exception("cleanup close() failed for %s", type(obj).__name__)


def check_response_size(resp: httpx.Response, label: str = "") -> None:
    """Raise if the response body exceeds the safety limit."""
    size = len(resp.content)
    if size > MAX_RESPONSE_BYTES:
        raise ValueError(
            f"Response from {label or resp.url.host} is {size:,} bytes, "
            f"exceeding {MAX_RESPONSE_BYTES:,} byte limit"
        )


def wait_with_retry_after(
    multiplier: float = 2,
    minimum: float = 2,
    maximum: float = 30,
) -> Any:
    """Wait strategy: Retry-After header on 429s, exponential backoff otherwise."""
    from tenacity import wait_exponential

    fallback = wait_exponential(multiplier=multiplier, min=minimum, max=maximum)

    def _wait(retry_state: Any) -> float:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
            header = exc.response.headers.get("Retry-After")
            if header is not None:
                try:
                    val = float(header)
                    if val != val:  # NaN check
                        pass
                    else:
                        return max(0.0, min(val, 120.0))
                except ValueError:
                    pass
        return fallback(retry_state=retry_state)

    return _wait


class AdapterFamily(str, enum.Enum):
    """What an adapter's output attaches to."""

    CREATOR_BOUND = "creator_bound"  # own content + audience (YouTube, Reddit, TikTok)
    NICHE = "niche"  # keyword-keyed problem reservoirs (Stack Exchange, reviews)
    CREATOR_WEB = "creator_web"  # the creator's web presence (shop, course, media kit)


class NormalizedContent(BaseModel):
    """The one schema every adapter family emits. This is the Build item.

    ``content_type`` values the collector understands:
    * content: video, short, post, reel, article, thread, story, page
    * interactions: comment, reply, question, review
    * creator profile: profile (metadata.follower_count, handle, display_name)
    * transcript: caption (parent_id = content external_id)
    """

    source_platform: str
    content_type: str
    external_id: str
    text: str
    author: str | None = None
    timestamp: datetime | None = None
    parent_id: str | None = None
    url: str | None = None
    access_method: AccessMethod
    compliance_status: ComplianceStatus
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceAdapter(ABC):
    """Abstract interface for all source adapters."""

    @property
    @abstractmethod
    def platform(self) -> str: ...

    @property
    def family(self) -> AdapterFamily:
        return AdapterFamily.CREATOR_BOUND

    @property
    @abstractmethod
    def access_method(self) -> AccessMethod: ...

    @property
    @abstractmethod
    def compliance_status(self) -> ComplianceStatus: ...

    @abstractmethod
    async def collect(self, identifier: str) -> list[NormalizedContent]: ...
