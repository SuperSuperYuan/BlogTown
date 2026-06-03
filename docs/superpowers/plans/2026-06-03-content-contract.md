# Content Data Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A code-level content contract — pydantic models, a validating filesystem loader, and an exported JSON Schema — that decouples Hermes-driven collection from the display site.

**Architecture:** Each collected item is one JSON file under `data/videos/<id>.json` or `data/blogs/<id>.json`. A discriminated-union pydantic model (on the `type` field) defines the schema for the two modalities. A loader reads a data directory, validates each file, skips/logs bad ones, and returns typed records sorted by publish date. A JSON Schema is generated from the models and committed as Hermes's output target.

**Tech Stack:** Python 3.11+, pydantic v2 (`TypeAdapter`, discriminated unions), pytest. No network/Hermes in tests.

**Spec:** `docs/superpowers/specs/2026-06-03-content-contract-design.md`

**Note on commands:** use the project venv — `.venv/bin/python` and `.venv/bin/pytest` (bare `python` is a different interpreter). Append this trailer to every commit body: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

- Create: `src/aishelf/contract/__init__.py` — package marker.
- Create: `src/aishelf/contract/models.py` — `ContentItem`, `VideoItem`, `BlogItem`, `parse_item`, `content_item_json_schema`.
- Create: `src/aishelf/contract/loader.py` — `load_items(data_dir)`.
- Create: `src/aishelf/contract/schema.py` — `write_schema()` + `python -m aishelf.contract.schema`.
- Create: `docs/contract/content-item.schema.json` — committed JSON Schema export.
- Create: `tests/fixtures/contract/videos/*.json`, `tests/fixtures/contract/blogs/*.json` (4 valid + 1 malformed).
- Create: `tests/unit/test_contract_models.py`, `tests/unit/test_contract_loader.py`, `tests/unit/test_contract_schema.py`.

---

## Task 1: Contract models

**Files:**
- Create: `src/aishelf/contract/__init__.py`
- Create: `src/aishelf/contract/models.py`
- Test: `tests/unit/test_contract_models.py`

- [ ] **Step 1: Create the package marker**

Create `src/aishelf/contract/__init__.py`:

```python
"""The content data contract shared by collection (Hermes) and the display site."""
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_contract_models.py`:

```python
import pytest
from pydantic import ValidationError

from aishelf.contract.models import BlogItem, VideoItem, parse_item

VIDEO = {
    "id": "youtube-abc",
    "type": "video",
    "title": "A talk",
    "author": "Some Author",
    "platform": "youtube",
    "source_url": "https://youtube.com/watch?v=abc",
    "published_at": "2024-01-02",
    "summary": "a summary",
    "keywords": ["ai", "talk"],
    "collected_at": "2024-01-03T10:00:00",
    "thumbnail_url": "https://img/abc.jpg",
    "duration_seconds": 100,
}

BLOG = {
    "id": "blog-xyz",
    "type": "blog",
    "title": "A post",
    "author": "Some Writer",
    "platform": "example.com",
    "source_url": "https://example.com/x",
    "published_at": "2024-02-01T08:00:00+00:00",
    "summary": "a summary",
    "keywords": [],
    "collected_at": "2024-02-02T10:00:00",
}


def test_parse_video_returns_videoitem():
    item = parse_item(VIDEO)
    assert isinstance(item, VideoItem)
    assert item.type == "video"
    assert item.duration_seconds == 100


def test_parse_blog_returns_blogitem():
    item = parse_item(BLOG)
    assert isinstance(item, BlogItem)
    assert item.type == "blog"
    assert item.keywords == []


def test_video_optional_fields_default_none():
    item = parse_item(BLOG)
    assert item.cover_image_url is None
    assert item.site_name is None


def test_missing_required_field_raises():
    bad = dict(VIDEO)
    del bad["title"]
    with pytest.raises(ValidationError):
        parse_item(bad)


def test_keywords_must_be_list_not_string():
    bad = dict(VIDEO)
    bad["keywords"] = "ai,talk"
    with pytest.raises(ValidationError):
        parse_item(bad)


def test_unknown_fields_ignored():
    extra = dict(VIDEO)
    extra["nonsense"] = 123
    item = parse_item(extra)
    assert not hasattr(item, "nonsense")


def test_unknown_type_raises():
    bad = dict(VIDEO)
    bad["type"] = "podcast"
    with pytest.raises(ValidationError):
        parse_item(bad)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_contract_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aishelf.contract.models'`.

- [ ] **Step 4: Implement the models**

Create `src/aishelf/contract/models.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_contract_models.py -v`
Expected: PASS (7 passed).

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/contract/__init__.py src/aishelf/contract/models.py tests/unit/test_contract_models.py
git commit -m "feat(contract): add video/blog pydantic models with discriminated parse"
```

---

## Task 2: Filesystem loader

**Files:**
- Create: `src/aishelf/contract/loader.py`
- Create: `tests/fixtures/contract/videos/youtube-aaa.json`
- Create: `tests/fixtures/contract/videos/bilibili-bbb.json`
- Create: `tests/fixtures/contract/videos/broken.json`
- Create: `tests/fixtures/contract/blogs/blog-ccc.json`
- Create: `tests/fixtures/contract/blogs/blog-ddd.json`
- Test: `tests/unit/test_contract_loader.py`

- [ ] **Step 1: Create the fixtures**

Create `tests/fixtures/contract/videos/youtube-aaa.json`:

```json
{
  "id": "youtube-aaa",
  "type": "video",
  "title": "March talk",
  "author": "Author One",
  "platform": "youtube",
  "source_url": "https://youtube.com/watch?v=aaa",
  "published_at": "2024-03-01",
  "summary": "March summary",
  "keywords": ["ai"],
  "collected_at": "2024-03-02T10:00:00",
  "thumbnail_url": "https://img/aaa.jpg",
  "duration_seconds": 600
}
```

Create `tests/fixtures/contract/videos/bilibili-bbb.json`:

```json
{
  "id": "bilibili-bbb",
  "type": "video",
  "title": "January talk",
  "author": "Author Two",
  "platform": "bilibili",
  "source_url": "https://bilibili.com/video/bbb",
  "published_at": "2024-01-15",
  "summary": "January summary",
  "keywords": [],
  "collected_at": "2024-01-16T10:00:00",
  "thumbnail_url": "https://img/bbb.jpg"
}
```

Create `tests/fixtures/contract/videos/broken.json` (intentionally malformed JSON):

```json
{ "id": "broken", not valid json
```

Create `tests/fixtures/contract/blogs/blog-ccc.json`:

```json
{
  "id": "blog-ccc",
  "type": "blog",
  "title": "February post",
  "author": "Writer One",
  "platform": "example.com",
  "source_url": "https://example.com/ccc",
  "published_at": "2024-02-10",
  "summary": "February summary",
  "keywords": ["llm", "research"],
  "collected_at": "2024-02-11T10:00:00",
  "site_name": "Example Blog"
}
```

Create `tests/fixtures/contract/blogs/blog-ddd.json`:

```json
{
  "id": "blog-ddd",
  "type": "blog",
  "title": "May post",
  "author": "Writer Two",
  "platform": "example.org",
  "source_url": "https://example.org/ddd",
  "published_at": "2024-05-01T08:30:00+00:00",
  "summary": "May summary",
  "keywords": ["agents"],
  "collected_at": "2024-05-02T10:00:00"
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_contract_loader.py`:

```python
from pathlib import Path

from aishelf.contract.loader import load_items

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"


def test_load_items_returns_valid_records_sorted_desc():
    items = load_items(FIXTURES)
    # 4 valid files; broken.json is skipped
    assert len(items) == 4
    # sorted by published_at descending: May, March, Feb, Jan
    assert [it.id for it in items] == [
        "blog-ddd",
        "youtube-aaa",
        "blog-ccc",
        "bilibili-bbb",
    ]


def test_load_items_skips_malformed_without_raising():
    items = load_items(FIXTURES)
    assert all(it.id != "broken" for it in items)


def test_load_items_missing_dir_returns_empty(tmp_path):
    assert load_items(tmp_path) == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_contract_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aishelf.contract.loader'`.

- [ ] **Step 4: Implement the loader**

Create `src/aishelf/contract/loader.py`:

```python
"""Read content records from a data directory, validating against the contract."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from aishelf.contract.models import ContentItem, parse_item

logger = logging.getLogger(__name__)

_MODALITY_DIRS = ("videos", "blogs")


def _parse_dt(value: str) -> datetime:
    """Parse an ISO date/datetime to a naive-UTC datetime for sorting.

    Unparseable values sort last (treated as the minimum).
    """
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def load_items(data_dir) -> list[ContentItem]:
    """Load and validate every record under `data_dir/{videos,blogs}`.

    Malformed JSON or records that fail validation are skipped and logged;
    they never abort the load. Results are sorted by `published_at` descending.
    """
    base = Path(data_dir)
    items: list[ContentItem] = []
    for sub in _MODALITY_DIRS:
        modality_dir = base / sub
        if not modality_dir.is_dir():
            continue
        for path in sorted(modality_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                items.append(parse_item(raw))
            except (json.JSONDecodeError, ValidationError, OSError) as exc:
                logger.warning("skipping invalid content file %s: %s", path, exc)
                continue
    items.sort(key=lambda it: _parse_dt(it.published_at), reverse=True)
    return items
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_contract_loader.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/contract/loader.py tests/fixtures/contract
git add tests/unit/test_contract_loader.py
git commit -m "feat(contract): add validating filesystem loader with fixtures"
```

---

## Task 3: JSON Schema export

**Files:**
- Create: `src/aishelf/contract/schema.py`
- Create: `docs/contract/content-item.schema.json`
- Test: `tests/unit/test_contract_schema.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_contract_schema.py`:

```python
import json
from pathlib import Path

from aishelf.contract.models import content_item_json_schema

SCHEMA_FILE = (
    Path(__file__).resolve().parents[2] / "docs" / "contract" / "content-item.schema.json"
)


def test_committed_schema_matches_models():
    assert SCHEMA_FILE.exists(), "run `python -m aishelf.contract.schema` to generate it"
    committed = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    assert committed == content_item_json_schema()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_contract_schema.py -v`
Expected: FAIL — `AssertionError: run ... to generate it` (file does not exist yet).

- [ ] **Step 3: Implement the exporter**

Create `src/aishelf/contract/schema.py`:

```python
"""Export the content contract as a JSON Schema document (Hermes's output target).

Run `python -m aishelf.contract.schema` to (re)generate the committed file.
"""

from __future__ import annotations

import json
from pathlib import Path

from aishelf.contract.models import content_item_json_schema

DEFAULT_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "contract" / "content-item.schema.json"
)


def write_schema(path: Path = DEFAULT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(content_item_json_schema(), indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


if __name__ == "__main__":
    print(f"wrote {write_schema()}")
```

- [ ] **Step 4: Generate the schema file**

Run: `.venv/bin/python -m aishelf.contract.schema`
Expected: prints `wrote .../docs/contract/content-item.schema.json`, and the file now exists.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_contract_schema.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/contract/schema.py docs/contract/content-item.schema.json tests/unit/test_contract_schema.py
git commit -m "feat(contract): export content-item JSON Schema for Hermes"
```

---

## Task 4: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the whole default suite**

Run: `.venv/bin/pytest -q`
Expected: all tests pass (the webui tests plus the new contract tests), network tests deselected.

---

## Self-Review Notes

- **Spec coverage:** storage layout + atomic-write convention is documented in the spec and the schema export is Hermes-facing (Task 3); the *reader* side (loader) is fully implemented and tested (Task 2); models cover all required + optional fields for both modalities incl. `extra="ignore"` and the `type` discriminator (Task 1); fixtures live under `tests/fixtures/contract/` per the spec; malformed-file tolerance is tested (Task 2). The atomic *write* and `_failures/` are Hermes-side responsibilities (out of scope for this reader-side contract code) — captured in the spec, no code task here by design.
- **Type consistency:** `parse_item`, `content_item_json_schema`, `load_items`, `VideoItem`, `BlogItem`, `ContentItem` are named identically across models, loader, schema, and all tests. `_ADAPTER` is module-private and reused by both `parse_item` and `content_item_json_schema`.
- **Placeholder scan:** every code/JSON step contains complete content; the only intentionally invalid content is `broken.json`, which is meant to be malformed.
- **Path arithmetic:** `schema.py` is at `src/aishelf/contract/` so `parents[3]` = repo root; the test is at `tests/unit/` so `parents[2]` = repo root. Both resolve to `docs/contract/content-item.schema.json`.
