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
