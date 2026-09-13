import enum
from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, Field

from corp.core.models.evidence import AccessMethod, ComplianceStatus


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
    metadata: dict = Field(default_factory=dict)


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
