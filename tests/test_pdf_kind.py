from pathlib import Path

import pypdfium2 as pdfium

from src.pdf_kind import looks_like_deck_pdf, pdf_is_deck
from src.routing import file_kind


def _write_pdf(path: Path, width: float, height: float) -> None:
    doc = pdfium.PdfDocument.new()
    doc.new_page(width, height)
    doc.save(path)
    doc.close()


def test_excel_and_office_suffixes_are_fixed(tmp_path: Path) -> None:
    assert file_kind(tmp_path / "data.xlsx") == "tabular"
    assert file_kind(tmp_path / "macro.xlsm") == "tabular"
    assert file_kind(tmp_path / "deck.pptx") == "deck"
    assert file_kind(tmp_path / "notes.docx") == "document"


def test_a4_report_pdf_goes_mineru(tmp_path: Path) -> None:
    path = tmp_path / "report.pdf"
    _write_pdf(path, 595, 842)
    assert pdf_is_deck(path) is False
    assert file_kind(path) == "document"


def test_widescreen_slide_pdf_goes_qwen(tmp_path: Path) -> None:
    path = tmp_path / "export.pdf"
    _write_pdf(path, 960, 540)
    assert pdf_is_deck(path) is True
    assert file_kind(path) == "deck"


def test_powerpoint_producer_wins_over_a4() -> None:
    assert looks_like_deck_pdf(
        producer="Microsoft PowerPoint",
        creator="",
        page_sizes=[(595, 842)],
    )
    assert not looks_like_deck_pdf(
        producer="",
        creator="PDFium",
        page_sizes=[(595, 842)],
    )


def test_missing_pdf_defaults_to_document(tmp_path: Path) -> None:
    assert file_kind(tmp_path / "missing.pdf") == "document"
