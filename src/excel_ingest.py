from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from .excel.ir import TableBlock, load_workbook_tables, tables_from_grid
from .excel.layout import (
    classify_table,
    emit_table,
    maybe_column_map,
    table_to_chunks,
)
from .excel.survey import (
    build_question_catalog,
    catalog_chunks,
    skip_duplicate_crosstab_sheet,
    SURVEY_SCHEMA_TEXT,
)

# Test and CLI compatibility aliases.
_tables_from_grid = tables_from_grid
_skip_duplicate_crosstab_sheet = skip_duplicate_crosstab_sheet


def parse_tabular_input(
    input_path: Path,
    work: Path,
    track: str = "knowledge",
) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    name = input_path.name.lower()
    long_rows: list[dict[str, Any]] = []
    catalog: list[dict[str, Any]] = []
    table_kind: str | None = None
    schema_text: str | None = None
    if name.endswith(".jsonl.gz") or name.endswith(".jsonl"):
        chunks = _load_jsonl(input_path)
    elif input_path.suffix.lower() in {".xlsx", ".xlsm"}:
        parsed = parse_excel_workbook_result(input_path, track=track)
        chunks = parsed["chunks"]
        long_rows = parsed["sql_rows"]
        catalog = parsed["catalog"]
        table_kind = parsed["table_kind"]
        schema_text = parsed["schema_text"]
    else:
        raise RuntimeError(f"unsupported tabular input: {input_path.name}")
    if not chunks:
        raise RuntimeError(f"no chunks produced from {input_path.name}")
    corpus = {
        "filename": input_path.name,
        "source_type": "excel",
        "chunks": chunks,
    }
    dest = work / "doc_corpus.json"
    dest.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if long_rows:
        _write_jsonl_gz(work / "table_rows.jsonl.gz", long_rows)
        (work / "question_catalog.json").write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        kind = table_kind if table_kind in {"survey", "generic"} else "generic"
        (work / "table_meta.json").write_text(
            json.dumps(
                {
                    "table_kind": kind,
                    "schema_text": schema_text
                    or (SURVEY_SCHEMA_TEXT if kind == "survey" else ""),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return dest


def excel_to_chunks(path: Path, track: str = "knowledge") -> list[dict[str, Any]]:
    chunks, _long_rows, _catalog = parse_excel_workbook(path, track=track)
    return chunks


def parse_excel_workbook(
    path: Path, track: str = "knowledge"
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    parsed = parse_excel_workbook_result(path, track=track)
    return parsed["chunks"], parsed["sql_rows"] if parsed["table_kind"] == "survey" else [], parsed["catalog"] if parsed["table_kind"] == "survey" else []


def parse_excel_workbook_result(path: Path, track: str = "knowledge") -> dict[str, Any]:
    tables = load_workbook_tables(path)
    chunks: list[dict[str, Any]] = []
    survey_rows: list[dict[str, Any]] = []
    generic_rows: list[dict[str, Any]] = []
    generic_catalog: list[dict[str, Any]] = []
    schema_text: str | None = None
    for table in tables:
        emitted = emit_table(table, path.name, track)
        if emitted.kind == "skipped":
            continue
        chunks.extend(emitted.chunks)
        if emitted.table_kind == "survey":
            survey_rows.extend(emitted.sql_rows)
            if emitted.schema_text:
                schema_text = emitted.schema_text
        elif emitted.table_kind == "generic":
            generic_rows.extend(emitted.sql_rows)
            generic_catalog.extend(emitted.catalog)
            if emitted.schema_text and schema_text is None:
                schema_text = emitted.schema_text
    catalog = build_question_catalog(survey_rows)
    chunks.extend(catalog_chunks(catalog, path.name))
    if survey_rows:
        return {
            "chunks": chunks,
            "sql_rows": survey_rows,
            "catalog": catalog,
            "table_kind": "survey",
            "schema_text": schema_text or SURVEY_SCHEMA_TEXT,
        }
    return {
        "chunks": chunks,
        "sql_rows": generic_rows,
        "catalog": generic_catalog,
        "table_kind": "generic" if generic_rows else None,
        "schema_text": schema_text,
    }


def _write_jsonl_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    opener = gzip.open if path.name.lower().endswith(".gz") else open
    rows: list[dict[str, Any]] = []
    with opener(path, "rt", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            line = line.strip()
            if not line:
                continue
            parsed = json.loads(line)
            text = str(parsed.get("text") or "").strip()
            if not text:
                continue
            rows.append(
                {
                    "id": str(parsed.get("id") or f"row_{index}"),
                    "text": text,
                    "metadata": dict(parsed.get("metadata") or {}),
                }
            )
    return rows


__all__ = [
    "TableBlock",
    "classify_table",
    "excel_to_chunks",
    "load_workbook_tables",
    "maybe_column_map",
    "parse_excel_workbook",
    "parse_excel_workbook_result",
    "parse_tabular_input",
    "table_to_chunks",
    "_skip_duplicate_crosstab_sheet",
    "_tables_from_grid",
]
