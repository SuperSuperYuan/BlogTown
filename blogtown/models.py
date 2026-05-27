from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Post:
    slug: str
    title: str
    body: str
    created_at: str

    @classmethod
    def create(cls, slug: str, title: str, body: str) -> "Post":
        return cls(
            slug=slug,
            title=title,
            body=body,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Post":
        return cls(
            slug=str(data["slug"]),
            title=str(data["title"]),
            body=str(data["body"]),
            created_at=str(data["created_at"]),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "slug": self.slug,
            "title": self.title,
            "body": self.body,
            "created_at": self.created_at,
        }
