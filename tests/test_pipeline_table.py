import json
from pathlib import Path

from src.pipeline import _copy_sql_table_sidecars, write_jsonl_gz


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
        __import__("gzip").open(bundle / "crosstab_long.jsonl.gz", "rt", encoding="utf-8").read().splitlines()[0]
    )
    assert rows["document_id"] == "doc-9"
    assert (bundle / "question_catalog.json").is_file()

    from src.pipeline import load_bundle_table

    payload = load_bundle_table(bundle)
    assert payload is not None
    assert payload["rows"][0]["option"] == "25-34"
    assert payload["catalog"][0]["question"] == "Age"
