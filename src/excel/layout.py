from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Protocol

from ..config import get_settings
from .aliases import (
    CODEBOOK_CODE_ALIASES,
    CODEBOOK_LABEL_ALIASES,
    CODEBOOK_VARIABLE_ALIASES,
    KV_LEFT_ALIASES,
    KV_RIGHT_ALIASES,
    PERSONA_ID_KEYS,
    PERSONA_KEYS,
    QUESTION_ALIASES,
    aliases_regex,
)
from .cells import cell_str, is_number, sql_ident
from .ir import TableBlock
from .survey import (
    SURVEY_SCHEMA_TEXT,
    crosstab_chunks_from_records,
    crosstab_records,
    materialize_crosstab_table,
    skip_duplicate_crosstab_sheet,
    survey_crosstab_score,
    unpivot_crosstab_records,
)

Q_CODE = re.compile(r"^q\d", re.I)
QUESTION_HINTS = aliases_regex(QUESTION_ALIASES)
CODEBOOK_VARIABLE = aliases_regex(CODEBOOK_VARIABLE_ALIASES)
CODEBOOK_CODE = aliases_regex(CODEBOOK_CODE_ALIASES, as_word=True)
CODEBOOK_LABEL = aliases_regex(CODEBOOK_LABEL_ALIASES)
KV_LEFT = aliases_regex(KV_LEFT_ALIASES)
KV_RIGHT = aliases_regex(KV_RIGHT_ALIASES)
ROW_GROUP = 20


@dataclass
class LayoutEmit:
    kind: str
    table_kind: str | None = None
    chunks: list[dict[str, Any]] = field(default_factory=list)
    sql_rows: list[dict[str, Any]] = field(default_factory=list)
    catalog: list[dict[str, Any]] = field(default_factory=list)
    schema_text: str | None = None


class LayoutAdapter(Protocol):
    name: str
    kind: str

    def score(self, table: TableBlock) -> float: ...

    def emit(self, table: TableBlock, source_file: str, track: str) -> LayoutEmit: ...


def chunk(chunk_id: str, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {"id": chunk_id, "text": text, "metadata": metadata}


def mapped_header(table: TableBlock, header: str) -> str:
    mapped = table.column_map.get(header) or {}
    label = str(mapped.get("label") or "").strip()
    return label or header


def notes_score(table: TableBlock) -> float:
    if not table.headers and not table.rows:
        return 0.99
    filled_max = 0
    for _excel_row, values in table.rows:
        filled_max = max(filled_max, sum(1 for v in values if cell_str(v)))
    if filled_max <= 1 and len(table.headers) <= 1:
        return 0.95
    if not table.rows:
        return 0.9
    return 0.0


def looks_like_codebook(headers: list[str]) -> bool:
    if len(headers) < 2:
        return False
    blob = " ".join(headers)
    hits = 0
    if CODEBOOK_VARIABLE.search(blob):
        hits += 1
    if CODEBOOK_CODE.search(blob):
        hits += 1
    if CODEBOOK_LABEL.search(blob):
        hits += 1
    return hits >= 2


def looks_like_kv_form(headers: list[str], rows: list[tuple[int, list[Any]]]) -> bool:
    if len(headers) != 2 or not rows:
        return False
    left = headers[0]
    right = headers[1]
    if KV_LEFT.search(left) and KV_RIGHT.search(right):
        return True
    first_col = [cell_str(values[0] if values else "") for _, values in rows]
    filled = [v for v in first_col if v]
    if len(filled) < 3 or len(set(filled)) != len(filled):
        return False
    if any(Q_CODE.match(h.replace(" ", "")) for h in headers):
        return False
    return median(len(v) for v in filled) <= 24


def looks_like_matrix(headers: list[str], rows: list[tuple[int, list[Any]]]) -> bool:
    first_header = headers[0] if headers else ""
    first_col = [cell_str(values[0] if values else "") for _, values in rows]
    other_vals = [
        cell_str(v)
        for _, values in rows
        for v in values[1:]
        if cell_str(v)
    ]
    long_questions = bool(first_col) and median(len(v) for v in first_col) >= 40
    low_cardinality = bool(other_vals) and len(set(other_vals)) / max(len(other_vals), 1) <= 0.25
    return bool(QUESTION_HINTS.search(first_header) or (long_questions and low_cardinality))


def fill_ratio(table: TableBlock) -> float:
    width = max(len(table.headers), 1)
    cells = width * max(len(table.rows), 1)
    filled = sum(1 for _, row in table.rows for v in row[:width] if cell_str(v))
    return filled / cells


def is_messy(table: TableBlock) -> bool:
    return len(table.headers) >= 8 and fill_ratio(table) < 0.25


class NotesAdapter:
    name = "notes"
    kind = "notes"

    def score(self, table: TableBlock) -> float:
        return notes_score(table)

    def emit(self, table: TableBlock, source_file: str, track: str) -> LayoutEmit:
        body = "\n".join(
            " | ".join(cell_str(v) for v in row if cell_str(v))
            for _, row in table.rows
        ).strip()
        chunks = []
        if body:
            chunks.append(chunk(
                f"{table.sheet}_notes",
                f"Sheet {table.sheet}\n{body}",
                {
                    "excel_sheet": table.sheet,
                    "sheet_kind": "notes",
                    "chunk_type": "excel_notes",
                    "source_file": source_file,
                },
            ))
        return LayoutEmit(kind=self.kind, chunks=chunks)


class SurveyCrosstabAdapter:
    name = "survey_crosstab"
    kind = "crosstab"

    def score(self, table: TableBlock) -> float:
        return survey_crosstab_score(table)

    def emit(self, table: TableBlock, source_file: str, track: str) -> LayoutEmit:
        if skip_duplicate_crosstab_sheet(table.sheet):
            return LayoutEmit(kind="skipped")
        ready = materialize_crosstab_table(table)
        records = crosstab_records(ready)
        chunks = crosstab_chunks_from_records(ready, records, source_file)
        sql_rows = unpivot_crosstab_records(records, ready.sheet, source_file)
        return LayoutEmit(
            kind=self.kind,
            table_kind="survey",
            chunks=chunks,
            sql_rows=sql_rows,
            schema_text=SURVEY_SCHEMA_TEXT,
        )


class CodebookAdapter:
    name = "codebook"
    kind = "codebook"

    def score(self, table: TableBlock) -> float:
        return 0.85 if looks_like_codebook(table.headers) else 0.0

    def emit(self, table: TableBlock, source_file: str, track: str) -> LayoutEmit:
        headers = [mapped_header(table, h) for h in table.headers]
        return LayoutEmit(kind=self.kind, chunks=_codebook_chunks(table, headers, source_file))


class KvFormAdapter:
    name = "kv_form"
    kind = "kv_form"

    def score(self, table: TableBlock) -> float:
        return 0.75 if looks_like_kv_form(table.headers, table.rows) else 0.0

    def emit(self, table: TableBlock, source_file: str, track: str) -> LayoutEmit:
        headers = [mapped_header(table, h) for h in table.headers]
        return LayoutEmit(kind=self.kind, chunks=_kv_chunks(table, headers, source_file))


class MatrixAdapter:
    name = "matrix_questionnaire"
    kind = "matrix_questionnaire"

    def score(self, table: TableBlock) -> float:
        return 0.65 if looks_like_matrix(table.headers, table.rows) else 0.0

    def emit(self, table: TableBlock, source_file: str, track: str) -> LayoutEmit:
        return LayoutEmit(
            kind=self.kind,
            chunks=_row_chunks(table, source_file, track, sheet_kind=self.kind),
        )


class GenericTidyAdapter:
    name = "generic_tidy"
    kind = "data_table"

    def score(self, table: TableBlock) -> float:
        if notes_score(table) > 0:
            return 0.0
        if not table.headers or not table.rows:
            return 0.0
        if is_messy(table):
            return 0.2
        return 0.4

    def emit(self, table: TableBlock, source_file: str, track: str) -> LayoutEmit:
        chunks = _row_chunks(table, source_file, track, sheet_kind="data_table")
        sql_rows, schema_text, catalog = _generic_sql(table, source_file)
        chunks = [*chunks, _schema_chunk(table, source_file, schema_text)]
        return LayoutEmit(
            kind=self.kind,
            table_kind="generic",
            chunks=chunks,
            sql_rows=sql_rows,
            catalog=catalog,
            schema_text=schema_text,
        )


class StructureChunkAdapter:
    name = "structure_chunk"
    kind = "data_table"

    def score(self, table: TableBlock) -> float:
        if notes_score(table) > 0 or not table.rows:
            return 0.0
        return 0.25 if is_messy(table) else 0.05

    def emit(self, table: TableBlock, source_file: str, track: str) -> LayoutEmit:
        return LayoutEmit(
            kind=self.kind,
            chunks=_row_group_chunks(table, source_file),
        )


ADAPTERS: list[LayoutAdapter] = [
    NotesAdapter(),
    SurveyCrosstabAdapter(),
    CodebookAdapter(),
    KvFormAdapter(),
    MatrixAdapter(),
    GenericTidyAdapter(),
    StructureChunkAdapter(),
]


def select_adapter(table: TableBlock) -> LayoutAdapter:
    ranked = sorted(ADAPTERS, key=lambda adapter: adapter.score(table), reverse=True)
    return ranked[0]


def classify_table(headers: list[str], rows: list[tuple[int, list[Any]]]) -> str:
    table = TableBlock(sheet="", headers=headers, rows=rows, start_row=0, end_row=0)
    return select_adapter(table).kind


def maybe_column_map(table: TableBlock) -> dict[str, dict[str, str]]:
    s = get_settings()
    if (
        not s.excel_llm_columns
        or not s.llm_api_key.strip()
        or table.kind not in {"data_table", "matrix_questionnaire"}
    ):
        return {}
    samples = table.rows[:3]
    payload = {
        "sheet": table.sheet,
        "kind": table.kind,
        "headers": table.headers,
        "samples": [
            {table.headers[i]: cell_str(row[i] if i < len(row) else "") for i in range(len(table.headers))}
            for _, row in samples
        ],
    }
    try:
        return _llm_column_map(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"==> excel column map skipped: {exc}")
        return {}


def table_to_chunks(
    table: TableBlock,
    source_file: str,
    track: str = "knowledge",
) -> list[dict[str, Any]]:
    if table.kind == "notes":
        return NotesAdapter().emit(table, source_file, track).chunks
    if table.kind == "codebook":
        return CodebookAdapter().emit(table, source_file, track).chunks
    if table.kind == "crosstab":
        return SurveyCrosstabAdapter().emit(table, source_file, track).chunks
    if table.kind == "kv_form":
        return KvFormAdapter().emit(table, source_file, track).chunks
    if table.kind == "matrix_questionnaire":
        return MatrixAdapter().emit(table, source_file, track).chunks
    return _row_chunks(table, source_file, track, sheet_kind=table.kind or "data_table")


def emit_table(table: TableBlock, source_file: str, track: str) -> LayoutEmit:
    adapter = select_adapter(table)
    table.kind = adapter.kind
    table.column_map = maybe_column_map(table)
    return adapter.emit(table, source_file, track)


def _row_chunks(
    table: TableBlock,
    source_file: str,
    track: str,
    *,
    sheet_kind: str,
) -> list[dict[str, Any]]:
    headers = [mapped_header(table, h) for h in table.headers]
    chunks: list[dict[str, Any]] = []
    chunk_type = "excel_question" if sheet_kind == "matrix_questionnaire" else "excel_row"
    table_kind = "generic" if sheet_kind == "data_table" else None
    for excel_row, values in table.rows:
        parts: list[str] = []
        meta: dict[str, Any] = {
            "excel_row": excel_row,
            "excel_sheet": table.sheet,
            "sheet_kind": sheet_kind,
            "chunk_type": chunk_type,
            "source_file": source_file,
        }
        if table_kind:
            meta["table_kind"] = table_kind
        for key, val in zip(headers, values, strict=False):
            text_val = cell_str(val)
            if not text_val:
                continue
            parts.append(f"{key}: {text_val}")
            if track == "survey":
                key_l = key.lower()
                if key_l in PERSONA_KEYS and "persona" not in meta:
                    meta["persona"] = text_val
                if key_l in PERSONA_ID_KEYS:
                    meta["persona_id"] = text_val
        if not parts:
            continue
        prefix = f"Excel row {excel_row} | sheet {table.sheet} | {sheet_kind}"
        if meta.get("persona"):
            prefix += f" | {meta['persona']}"
        chunks.append(chunk(f"{table.sheet}_row_{excel_row}", f"{prefix}\n" + "\n".join(parts), meta))
    return chunks


def _codebook_chunks(
    table: TableBlock,
    headers: list[str],
    source_file: str,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current_var = ""
    parts: list[str] = []
    start_row = 0
    for excel_row, values in table.rows:
        row_map = {
            headers[i]: cell_str(values[i] if i < len(values) else "")
            for i in range(len(headers))
        }
        var = row_map.get(headers[0], "") if headers else ""
        if var and var != current_var and parts:
            chunks.append(chunk(
                f"{table.sheet}_var_{start_row}",
                f"Sheet {table.sheet} | codebook\n" + "\n".join(parts),
                {
                    "excel_sheet": table.sheet,
                    "excel_row": start_row,
                    "sheet_kind": "codebook",
                    "chunk_type": "excel_codebook",
                    "source_file": source_file,
                    "variable": current_var,
                },
            ))
            parts = []
        if var:
            current_var = var
            start_row = excel_row
        line = " | ".join(f"{k}: {v}" for k, v in row_map.items() if v)
        if line:
            parts.append(line)
    if parts:
        chunks.append(chunk(
            f"{table.sheet}_var_{start_row}",
            f"Sheet {table.sheet} | codebook\n" + "\n".join(parts),
            {
                "excel_sheet": table.sheet,
                "excel_row": start_row,
                "sheet_kind": "codebook",
                "chunk_type": "excel_codebook",
                "source_file": source_file,
                "variable": current_var,
            },
        ))
    return chunks


def _kv_chunks(
    table: TableBlock,
    headers: list[str],
    source_file: str,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    left = headers[0] if headers else "field"
    right = headers[1] if len(headers) > 1 else "value"
    for excel_row, values in table.rows:
        key = cell_str(values[0] if values else "")
        val = cell_str(values[1] if len(values) > 1 else "")
        if not key and not val:
            continue
        label = key or left
        text = f"Excel row {excel_row} | sheet {table.sheet} | kv_form\n{label}: {val}"
        if key and val and left.lower() not in {"field", "key", "label"}:
            text = (
                f"Excel row {excel_row} | sheet {table.sheet} | kv_form\n"
                f"{left}: {key}\n{right}: {val}"
            )
        chunks.append(chunk(
            f"{table.sheet}_kv_{excel_row}",
            text,
            {
                "excel_row": excel_row,
                "excel_sheet": table.sheet,
                "sheet_kind": "kv_form",
                "chunk_type": "excel_kv",
                "source_file": source_file,
            },
        ))
    return chunks


def _row_group_chunks(table: TableBlock, source_file: str) -> list[dict[str, Any]]:
    headers = [mapped_header(table, h) for h in table.headers]
    header_line = " | ".join(headers)
    chunks: list[dict[str, Any]] = []
    rows = [(excel_row, values) for excel_row, values in table.rows]
    for start in range(0, len(rows), ROW_GROUP):
        group = rows[start : start + ROW_GROUP]
        lines = [f"Excel rows {group[0][0]}-{group[-1][0]} | sheet {table.sheet}", header_line]
        for excel_row, values in group:
            cells = [cell_str(v) for v in values[: len(headers)]]
            if not any(cells):
                continue
            lines.append(" | ".join(cells))
        if len(lines) <= 2:
            continue
        chunks.append(chunk(
            f"{table.sheet}_rows_{group[0][0]}",
            "\n".join(lines),
            {
                "excel_row": group[0][0],
                "excel_sheet": table.sheet,
                "sheet_kind": "data_table",
                "chunk_type": "excel_row_group",
                "source_file": source_file,
            },
        ))
    return chunks


def _generic_sql(
    table: TableBlock,
    source_file: str,
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    headers = [mapped_header(table, h) for h in table.headers]
    names: list[str] = []
    seen: set[str] = set()
    for index, header in enumerate(headers):
        name = sql_ident(header, index)
        if name in seen:
            name = f"{name}_{index}"
        seen.add(name)
        names.append(name)
    sql_rows: list[dict[str, Any]] = []
    types = {name: "number" for name in names}
    for excel_row, values in table.rows:
        row: dict[str, Any] = {
            "source_file": source_file,
            "sheet": table.sheet,
            "excel_row": excel_row,
        }
        empty = True
        for index, name in enumerate(names):
            raw = cell_str(values[index] if index < len(values) else "")
            if not raw:
                row[name] = None
                continue
            empty = False
            if is_number(raw):
                row[name] = float(raw.replace(",", ""))
            else:
                row[name] = raw
                types[name] = "text"
        if not empty:
            sql_rows.append(row)
    col_lines = []
    for header, name in zip(headers, names, strict=False):
        dtype = "DOUBLE" if types[name] == "number" else "VARCHAR"
        col_lines.append(f"  {name} {dtype},  -- {header}")
    schema_text = (
        "Table data (\n"
        "  document_id VARCHAR,\n"
        "  source_file VARCHAR,\n"
        "  sheet VARCHAR,\n"
        "  excel_row INTEGER,\n"
        + "\n".join(col_lines)
        + "\n)\nThe DuckDB view is named data. Use only these columns; copy text filters exactly.\n"
        "Do not invent column names. document_id / source_file / sheet / excel_row are provenance."
    )
    catalog = [
        {
            "sheet": table.sheet,
            "columns": headers,
            "sql_columns": names,
            "row_count": len(sql_rows),
        }
    ]
    return sql_rows, schema_text, catalog


def _schema_chunk(table: TableBlock, source_file: str, schema_text: str) -> dict[str, Any]:
    headers = [mapped_header(table, h) for h in table.headers]
    preview = ", ".join(headers[:24])
    if len(headers) > 24:
        preview += ", …"
    text = (
        f"Table catalog | {source_file}\n"
        f"Sheet: {table.sheet}\n"
        f"Kind: generic\n"
        f"Columns ({len(headers)}): {preview}\n"
        "Look up rows in the document table with SQL against view data."
    )
    return chunk(
        f"schema_{table.sheet}",
        text,
        {
            "excel_sheet": table.sheet,
            "sheet_kind": "data_table",
            "chunk_type": "excel_schema",
            "table_kind": "generic",
            "source_file": source_file,
            "schema_text": schema_text,
        },
    )


def _llm_column_map(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    import httpx

    s = get_settings()
    prompt = (
        "You label Excel columns for retrieval. Return JSON only: "
        '{"columns": {"<header>": {"label": "human name", "role": "id|measure|category|question|other", "unit": ""}}}.\n'
        "Keep labels short. Do not invent columns.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            s.llm_api_url,
            json={
                "model": s.llm_synth_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2048,
            },
            headers={
                "Authorization": f"Bearer {s.llm_api_key}",
                "Content-Type": "application/json",
            },
        )
    if resp.is_error:
        raise RuntimeError(f"Excel map HTTP {resp.status_code}: {resp.text[:300]}")
    raw = resp.json()["choices"][0]["message"]["content"]
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    parsed = json.loads(raw[start : end + 1])
    columns = parsed.get("columns") if isinstance(parsed, dict) else None
    if not isinstance(columns, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for key, value in columns.items():
        if isinstance(value, dict):
            out[str(key)] = {
                "label": str(value.get("label") or key),
                "role": str(value.get("role") or "other"),
                "unit": str(value.get("unit") or ""),
            }
    return out
