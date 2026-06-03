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
