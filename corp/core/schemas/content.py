from datetime import datetime

from pydantic import BaseModel, ConfigDict

from corp.core.models.content import ContentType, InteractionType


class ContentItemCreate(BaseModel):
    creator_id: str
    platform: str
    external_id: str
    title: str | None = None
    description: str | None = None
    content_type: ContentType
    published_at: datetime | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    url: str | None = None


class ContentItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    creator_id: str
    platform: str
    external_id: str
    title: str | None
    content_type: ContentType
    published_at: datetime | None
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    url: str | None
    created_at: datetime


class InteractionCreate(BaseModel):
    content_item_id: str
    external_id: str
    text: str
    author_handle: str | None = None
    interaction_type: InteractionType = InteractionType.COMMENT
    posted_at: datetime | None = None
    like_count: int | None = None
    parent_id: str | None = None


class InteractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content_item_id: str
    external_id: str
    text: str
    author_handle: str | None
    interaction_type: InteractionType
    posted_at: datetime | None
    like_count: int | None
    parent_id: str | None
