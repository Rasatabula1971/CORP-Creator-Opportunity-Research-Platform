from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, Field

from corp.core.models.evidence import AccessMethod, ComplianceStatus


class NormalizedContent(BaseModel):
    """The one schema both adapter families emit. This is the Build item."""

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
    @abstractmethod
    def access_method(self) -> AccessMethod: ...

    @property
    @abstractmethod
    def compliance_status(self) -> ComplianceStatus: ...

    @abstractmethod
    async def collect(self, identifier: str) -> list[NormalizedContent]: ...
