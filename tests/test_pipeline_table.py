import json
from pathlib import Path

from src.pipeline import _copy_sql_table_sidecars, load_bundle_table, write_jsonl_gz
from src.table_sidecar import resolve_table_kind


def test_copy_sql_table_sidecars_stamps_document_id(tmp_path: Path) -> None:
    parse_dir = tmp_path / "parse"
    parse_dir.mkdir()
    write_jsonl_gz(
        parse_dir / "crosstab_long.jsonl.gz",
        [{"question": "Age", "option": "25-34", "country": "Japan", "metric": "pct", "value": 0.079}],
    )
    (parse_dir / "question_catalog.json").write_text(
        json.dumps([{"question": "Age", "options": ["25-34"]}]) + "\n",
        encoding="utf-8",
    )
    (parse_dir / "doc_corpus.json").write_text("{}\n", encoding="utf-8")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    assert _copy_sql_table_sidecars(parse_dir / "doc_corpus.json", bundle, "doc-9") is True
    rows = json.loads(
        __import__("gzip").open(bundle / "table_rows.jsonl.gz", "rt", encoding="utf-8").read().splitlines()[0]
    )
    assert rows["document_id"] == "doc-9"
    assert (bundle / "question_catalog.json").is_file()

    payload = load_bundle_table(bundle)
    assert payload is not None
    assert payload["rows"][0]["option"] == "25-34"
    assert payload["catalog"][0]["question"] == "Age"
    assert payload["table_kind"] == "survey"


def test_resolve_table_kind_defaults_old_bundles_to_survey() -> None:
    assert resolve_table_kind(None) == ("survey", None)
    assert resolve_table_kind({}) == ("survey", None)
    assert resolve_table_kind({"table_kind": ""}) == ("survey", None)
    kind, schema = resolve_table_kind({"table_kind": "generic", "schema_text": "Table data ()"})
    assert kind == "generic"
    assert schema == "Table data ()"
    assert resolve_table_kind({"table_kind": "finance"})[0] == "generic"


def test_load_bundle_table_reads_generic_meta(tmp_path: Path) -> None:
    write_jsonl_gz(tmp_path / "table_rows.jsonl.gz", [{"Region": "EU", "Units": 10}])
    (tmp_path / "table_meta.json").write_text(
        json.dumps({"table_kind": "generic", "schema_text": "Table data ()"}) + "\n",
        encoding="utf-8",
    )
    payload = load_bundle_table(tmp_path)
    assert payload is not None
    assert payload["table_kind"] == "generic"
    assert payload["schema_text"] == "Table data ()"

