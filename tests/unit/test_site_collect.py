from pathlib import Path

from aishelf.site.collect import build_collection_instructions


def test_instructions_contain_abs_paths_rules_and_schema(tmp_path):
    schema = tmp_path / "schema.json"
    schema.write_text('{"title": "ContentItem", "marker": "SCHEMA_BODY_123"}', encoding="utf-8")
    data_dir = tmp_path / "mydata"

    text = build_collection_instructions(data_dir, schema_path=schema)

    abs_data = str(data_dir.resolve())
    assert abs_data in text
    assert f"{abs_data}/videos/" in text
    assert f"{abs_data}/blogs/" in text
    # write conventions
    assert ".json.tmp" in text and "rename" in text
    # generated fields + content rules
    assert "summary" in text and "keywords" in text and "thumbnail_url" in text
    # the schema body is embedded verbatim
    assert "SCHEMA_BODY_123" in text


def test_default_schema_path_points_at_committed_schema():
    from aishelf.site import collect
    assert collect.SCHEMA_PATH.name == "content-item.schema.json"
    assert collect.SCHEMA_PATH.exists()
