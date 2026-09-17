from __future__ import annotations

from typing import Any


def cell_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def is_number(value: str) -> bool:
    try:
        float(value.replace(",", ""))
        return True
    except ValueError:
        return False


def filled_count(row: list[Any]) -> int:
    return sum(1 for v in row if cell_str(v))


def is_empty_row(row: list[Any]) -> bool:
    return filled_count(row) == 0


def mostly_numeric(row: list[Any]) -> bool:
    filled = [cell_str(v) for v in row if cell_str(v)]
    if not filled:
        return False
    numeric = sum(1 for v in filled if is_number(v))
    return numeric / len(filled) >= 0.5


def looks_like_header(row: list[Any]) -> bool:
    filled = [cell_str(v) for v in row if cell_str(v)]
    if len(filled) < 2:
        return False
    numeric = sum(1 for v in filled if is_number(v))
    return numeric / len(filled) <= 0.3


def row_width(rows: list[tuple[int, list[Any]]]) -> int:
    if not rows:
        return 1
    return max(len(values) for _, values in rows)


def trim_rows(rows: list[tuple[int, list[Any]]], width: int) -> list[tuple[int, list[Any]]]:
    out: list[tuple[int, list[Any]]] = []
    for excel_row, values in rows:
        padded = list(values) + [None] * max(0, width - len(values))
        out.append((excel_row, padded[:width]))
    return out


def sql_ident(header: str, index: int) -> str:
    import re

    slug = re.sub(r"[^A-Za-z0-9_]+", "_", (header or "").strip())
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug:
        slug = f"col_{index}"
    if slug[0].isdigit():
        slug = f"c_{slug}"
    return slug[:64]
