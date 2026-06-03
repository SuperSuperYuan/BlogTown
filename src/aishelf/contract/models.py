"""Pydantic models defining the content contract.

A record is one video or one blog/document, stored as a single JSON file.
The `type` field discriminates the two modalities.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class ContentItem(BaseModel):
    """Fields shared by every collected record."""

    model_config = ConfigDict(extra="ignore")

    id: str
    type: str
    title: str
    author: str
    platform: str
    source_url: str
    published_at: str
    summary: str
    keywords: list[str]
    collected_at: str


class VideoItem(ContentItem):
    type: Literal["video"] = "video"
    thumbnail_url: str
    duration_seconds: int | None = None
    embed_url: str | None = None
    author_id: str | None = None


class BlogItem(ContentItem):
    type: Literal["blog"] = "blog"
    cover_image_url: str | None = None
    site_name: str | None = None
    author_id: str | None = None


AnyContentItem = Annotated[Union[VideoItem, BlogItem], Field(discriminator="type")]

_ADAPTER: TypeAdapter = TypeAdapter(AnyContentItem)


def parse_item(data: dict) -> ContentItem:
    """Validate a raw dict into the right ContentItem subtype based on `type`."""
    return _ADAPTER.validate_python(data)


def content_item_json_schema() -> dict:
    """The JSON Schema for a content record (the union of both modalities)."""
    return _ADAPTER.json_schema()
