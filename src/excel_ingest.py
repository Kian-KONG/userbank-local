from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

from .config import get_settings

SheetKind = str

QUESTION_HINTS = re.compile(r"(question|frage|item|statement|item.?text)", re.I)
Q_CODE = re.compile(r"^q\d", re.I)
PERSONA_KEYS = {"persona", "persona_name"}
PERSONA_ID_KEYS = {"persona_id", "personaid"}


@dataclass
class TableBlock:
    sheet: str
    headers: list[str]
    rows: list[tuple[int, list[Any]]]
    start_row: int
    end_row: int
    kind: SheetKind = "data_table"
    column_map: dict[str, dict[str, str]] = field(default_factory=dict)


def parse_tabular_input(
    input_path: Path,
    work: Path,
    track: str = "knowledge",
) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    name = input_path.name.lower()
    if name.endswith(".jsonl.gz") or name.endswith(".jsonl"):
        chunks = _load_jsonl(input_path)
    elif input_path.suffix.lower() in {".xlsx", ".xlsm"}:
        chunks = excel_to_chunks(input_path, track=track)
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
    return dest


def excel_to_chunks(path: Path, track: str = "knowledge") -> list[dict[str, Any]]:
    tables = load_workbook_tables(path)
    chunks: list[dict[str, Any]] = []
    for table in tables:
        table.kind = classify_table(table.headers, table.rows)
        table.column_map = maybe_column_map(table)
        chunks.extend(table_to_chunks(table, path.name, track=track))
    return chunks


def load_workbook_tables(path: Path) -> list[TableBlock]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl required for xlsx parse — pip install openpyxl") from exc

    wb = load_workbook(path, data_only=True)
    tables: list[TableBlock] = []
    try:
        for sheet in wb.worksheets:
            grid = _sheet_grid(sheet)
            tables.extend(_tables_from_grid(sheet.title, grid))
    finally:
        wb.close()
    if not tables:
        raise RuntimeError(f"no data tables found in {path}")
    return tables


def classify_table(headers: list[str], rows: list[tuple[int, list[Any]]]) -> SheetKind:
    if not headers and not rows:
        return "notes"
    filled_max = 0
    for _excel_row, values in rows:
        filled_max = max(filled_max, sum(1 for v in values if _cell_str(v)))
    if filled_max <= 1 and len(headers) <= 1:
        return "notes"

    if _looks_like_codebook(headers):
        return "codebook"
    if _looks_like_kv_form(headers, rows):
        return "kv_form"

    first_header = headers[0] if headers else ""
    first_col = [_cell_str(values[0] if values else "") for _, values in rows]
    other_vals = [
        _cell_str(v)
        for _, values in rows
        for v in values[1:]
        if _cell_str(v)
    ]
    long_questions = bool(first_col) and median(len(v) for v in first_col) >= 40
    low_cardinality = bool(other_vals) and len(set(other_vals)) / max(len(other_vals), 1) <= 0.25
    if QUESTION_HINTS.search(first_header) or (long_questions and low_cardinality):
        return "matrix_questionnaire"
    if any(Q_CODE.match(h.replace(" ", "")) for h in headers):
        return "data_table"
    if not rows:
        return "notes"
    return "data_table"


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
            {table.headers[i]: _cell_str(row[i] if i < len(row) else "") for i in range(len(table.headers))}
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
    headers = [_mapped_header(table, h) for h in table.headers]
    if table.kind == "notes":
        body = "\n".join(
            " | ".join(_cell_str(v) for v in row if _cell_str(v))
            for _, row in table.rows
        ).strip()
        if not body:
            return []
        return [_chunk(
            f"{table.sheet}_notes",
            f"Sheet {table.sheet}\n{body}",
            {
                "excel_sheet": table.sheet,
                "sheet_kind": "notes",
                "chunk_type": "excel_notes",
                "source_file": source_file,
            },
        )]

    if table.kind == "codebook":
        return _codebook_chunks(table, headers, source_file)

    chunks: list[dict[str, Any]] = []
    for excel_row, values in table.rows:
        parts: list[str] = []
        meta: dict[str, Any] = {
            "excel_row": excel_row,
            "excel_sheet": table.sheet,
            "sheet_kind": table.kind,
            "chunk_type": "excel_row" if table.kind != "matrix_questionnaire" else "excel_question",
            "source_file": source_file,
        }
        for key, val in zip(headers, values, strict=False):
            text_val = _cell_str(val)
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
        prefix = f"Excel row {excel_row} | sheet {table.sheet} | {table.kind}"
        if meta.get("persona"):
            prefix += f" | {meta['persona']}"
        chunks.append(_chunk(f"{table.sheet}_row_{excel_row}", f"{prefix}\n" + "\n".join(parts), meta))
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
            headers[i]: _cell_str(values[i] if i < len(values) else "")
            for i in range(len(headers))
        }
        var = row_map.get(headers[0], "") if headers else ""
        if var and var != current_var and parts:
            chunks.append(_chunk(
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
        chunks.append(_chunk(
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


def _mapped_header(table: TableBlock, header: str) -> str:
    mapped = table.column_map.get(header) or {}
    label = str(mapped.get("label") or "").strip()
    return label or header


def _chunk(chunk_id: str, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {"id": chunk_id, "text": text, "metadata": metadata}


def _sheet_grid(sheet: Any) -> list[list[Any]]:
    max_row = sheet.max_row or 0
    max_col = sheet.max_column or 0
    if max_row < 1 or max_col < 1:
        return []
    grid = [[None] * max_col for _ in range(max_row)]
    for row in sheet.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_col):
        for cell in row:
            grid[cell.row - 1][cell.column - 1] = cell.value
    for merged in sheet.merged_cells.ranges:
        value = grid[merged.min_row - 1][merged.min_col - 1]
        for row_i in range(merged.min_row, merged.max_row + 1):
            for col_i in range(merged.min_col, merged.max_col + 1):
                grid[row_i - 1][col_i - 1] = value
    return grid


def _tables_from_grid(sheet_name: str, grid: list[list[Any]]) -> list[TableBlock]:
    if not grid:
        return []
    tables: list[TableBlock] = []
    i = 0
    while i < len(grid):
        while i < len(grid) and _is_empty_row(grid[i]):
            i += 1
        if i >= len(grid):
            break
        header_start = _skip_title_rows(grid, i)
        header_end = _header_band_end(grid, header_start)
        headers = _join_headers(grid[header_start:header_end])
        data_start = header_end
        data_end = data_start
        while data_end < len(grid) and not _is_empty_row(grid[data_end]):
            data_end += 1
        rows = [
            (idx + 1, list(grid[idx]))
            for idx in range(data_start, data_end)
            if not _is_empty_row(grid[idx])
        ]
        if headers or rows:
            tables.append(
                TableBlock(
                    sheet=sheet_name,
                    headers=headers or [f"col_{n}" for n in range(_row_width(rows))],
                    rows=_trim_rows(rows, max(len(headers), 1)),
                    start_row=header_start + 1,
                    end_row=data_end,
                )
            )
        i = data_end + 1
    return tables


def _skip_title_rows(grid: list[list[Any]], start: int) -> int:
    i = start
    while i < len(grid) - 1:
        filled = _filled_count(grid[i])
        nxt = _filled_count(grid[i + 1])
        if filled <= 1 and nxt >= max(2, filled + 1) and not _mostly_numeric(grid[i + 1]):
            i += 1
            continue
        break
    return i


def _header_band_end(grid: list[list[Any]], start: int) -> int:
    end = start + 1
    while end < len(grid) and _looks_like_header(grid[end]) and not _is_empty_row(grid[end]):
        if _mostly_numeric(grid[end]):
            break
        end += 1
        if end - start >= 4:
            break
    return max(end, start + 1)


def _join_headers(header_rows: list[list[Any]]) -> list[str]:
    if not header_rows:
        return []
    width = max(len(row) for row in header_rows)
    headers: list[str] = []
    for col in range(width):
        parts: list[str] = []
        for row in header_rows:
            value = _cell_str(row[col] if col < len(row) else "")
            if value and value not in parts:
                parts.append(value)
        headers.append(" / ".join(parts) if parts else f"col_{col}")
    while len(headers) > 1 and headers[-1].startswith("col_"):
        headers.pop()
    return headers


def _trim_rows(rows: list[tuple[int, list[Any]]], width: int) -> list[tuple[int, list[Any]]]:
    out: list[tuple[int, list[Any]]] = []
    for excel_row, values in rows:
        padded = list(values) + [None] * max(0, width - len(values))
        out.append((excel_row, padded[:width]))
    return out


def _row_width(rows: list[tuple[int, list[Any]]]) -> int:
    if not rows:
        return 1
    return max(len(values) for _, values in rows)


def _looks_like_codebook(headers: list[str]) -> bool:
    if len(headers) < 2:
        return False
    blob = " ".join(headers)
    hits = 0
    if re.search(r"(variable|var_?name)\b", blob, re.I):
        hits += 1
    if re.search(r"\bcode\b", blob, re.I):
        hits += 1
    if re.search(
        r"(value.?label|\blabel\b|meaning|beschreibung|bezeichnung)", blob, re.I
    ):
        hits += 1
    return hits >= 2


def _looks_like_kv_form(
    headers: list[str],
    rows: list[tuple[int, list[Any]]],
) -> bool:
    if len(headers) != 2 or not rows:
        return False
    left = headers[0]
    right = headers[1]
    if re.search(r"(key|field|label|attribute|item)", left, re.I) and re.search(
        r"(value|val|content|answer)", right, re.I
    ):
        return True
    first_col = [_cell_str(values[0] if values else "") for _, values in rows]
    filled = [v for v in first_col if v]
    if len(filled) < 3 or len(set(filled)) != len(filled):
        return False
    if any(Q_CODE.match(h.replace(" ", "")) for h in headers):
        return False
    return median(len(v) for v in filled) <= 24


def _looks_like_header(row: list[Any]) -> bool:
    filled = [_cell_str(v) for v in row if _cell_str(v)]
    if len(filled) < 2:
        return False
    numeric = sum(1 for v in filled if _is_number(v))
    return numeric / len(filled) <= 0.3


def _mostly_numeric(row: list[Any]) -> bool:
    filled = [_cell_str(v) for v in row if _cell_str(v)]
    if not filled:
        return False
    numeric = sum(1 for v in filled if _is_number(v))
    return numeric / len(filled) >= 0.5


def _filled_count(row: list[Any]) -> int:
    return sum(1 for v in row if _cell_str(v))


def _is_empty_row(row: list[Any]) -> bool:
    return _filled_count(row) == 0


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_number(value: str) -> bool:
    try:
        float(value.replace(",", ""))
        return True
    except ValueError:
        return False


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
