from __future__ import annotations

from pathlib import Path
from typing import Any

TABLE_ROWS_FILES = ("table_rows.jsonl.gz", "crosstab_long.jsonl.gz")


def table_rows_path(directory: Path) -> Path | None:
    for name in TABLE_ROWS_FILES:
        path = directory / name
        if path.is_file():
            return path
    return None


def resolve_table_kind(meta: dict[str, Any] | None) -> tuple[str, Any]:
    """Old bundles without table_meta.json are survey tables."""
    if not isinstance(meta, dict):
        return "survey", None
    raw = meta.get("table_kind")
    if raw is None or str(raw).strip() == "":
        kind = "survey"
    else:
        kind = str(raw).strip().lower()
        if kind not in {"survey", "generic"}:
            kind = "generic"
    schema_text = meta.get("schema_text")
    return kind, schema_text
