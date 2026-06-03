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
