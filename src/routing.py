from __future__ import annotations

from pathlib import Path
from typing import Literal

from .office import DECK_SUFFIXES
from .pdf_kind import pdf_is_deck

FileKind = Literal["deck", "tabular", "document"]

EXCEL_SUFFIXES = {".xlsx", ".xlsm"}


def file_kind(path: Path) -> FileKind:
    """Suffix first; PDFs are split by layout (slides → vision, reports → MinerU)."""
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix in DECK_SUFFIXES:
        return "deck"
    if suffix in EXCEL_SUFFIXES or name.endswith(".jsonl") or name.endswith(".jsonl.gz"):
        return "tabular"
    if suffix == ".pdf" and pdf_is_deck(path):
        return "deck"
    return "document"
