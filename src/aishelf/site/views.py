"""Pure view logic over a list of ContentItem records (no HTTP)."""

from __future__ import annotations

from dataclasses import dataclass

from aishelf.contract.models import ContentItem


@dataclass
class Page:
    items: list[ContentItem]
    page: int
    per_page: int
    total: int

    @property
    def total_pages(self) -> int:
        if self.per_page <= 0:
            return 1
        return max(1, (self.total + self.per_page - 1) // self.per_page)

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


def videos(items: list[ContentItem]) -> list[ContentItem]:
    return [it for it in items if it.type == "video"]


def blogs(items: list[ContentItem]) -> list[ContentItem]:
    return [it for it in items if it.type == "blog"]


def search(items: list[ContentItem], q: str) -> list[ContentItem]:
    needle = (q or "").strip().lower()
    if not needle:
        return []
    out = []
    for it in items:
        haystack = [it.title, it.summary, *it.keywords]
        if any(needle in (s or "").lower() for s in haystack):
            out.append(it)
    return out


def by_keyword(items: list[ContentItem], kw: str) -> list[ContentItem]:
    needle = (kw or "").strip().lower()
    if not needle:
        return list(items)
    return [it for it in items if any(needle == k.lower() for k in it.keywords)]


def keyword_counts(items: list) -> list[tuple[str, int]]:
    """All distinct keywords with how many items carry each (case-insensitive
    grouping; a keyword repeated within one item counts once). Returns
    (display, count) sorted by count desc then display (case-insensitive) asc;
    `display` is the first-seen original casing for that lower-cased key."""
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for it in items:
        seen: set[str] = set()
        for k in getattr(it, "keywords", None) or []:
            key = k.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, k)
    pairs = [(display[k], counts[k]) for k in counts]
    pairs.sort(key=lambda p: (-p[1], p[0].lower()))
    return pairs


CO_TAGS_LIMIT = 12


def co_keywords(items, kw, *, limit: int = CO_TAGS_LIMIT) -> list[tuple[str, int]]:
    """Keywords that co-occur with `kw` among `items` (already carrying `kw`).

    Case-insensitive grouping, deduped per item, excludes `kw` itself; sorted by
    count desc then display (case-insensitive) asc; capped to `limit`. Mirrors
    keyword_counts. Returns (display, count) pairs."""
    needle = (kw or "").strip().lower()
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for it in items:
        seen: set[str] = set()
        for k in getattr(it, "keywords", None) or []:
            key = k.strip().lower()
            if not key or key == needle or key in seen:
                continue
            seen.add(key)
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, k)
    pairs = [(display[k], counts[k]) for k in counts]
    pairs.sort(key=lambda p: (-p[1], p[0].lower()))
    return pairs[:limit]


def author_key(item: ContentItem) -> str:
    return getattr(item, "author_id", None) or item.author


def by_author(items: list[ContentItem], key: str) -> list[ContentItem]:
    return [it for it in items if author_key(it) == key]


def paginate(items: list[ContentItem], page: int, per_page: int) -> Page:
    total = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page) if per_page > 0 else 1
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    return Page(items=items[start : start + per_page], page=page, per_page=per_page, total=total)
