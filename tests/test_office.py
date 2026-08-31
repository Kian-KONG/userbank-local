from pathlib import Path

from src.office import (
    DECK_SUFFIXES,
    WORD_SUFFIXES,
    _convert_timeout_seconds,
    convert_office_to_pdf,
)


def test_deck_suffixes_include_pptm() -> None:
    assert DECK_SUFFIXES == {".ppt", ".pptx", ".pptm"}
    assert WORD_SUFFIXES == {".doc", ".docx"}


def test_pdf_passthrough(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert convert_office_to_pdf(pdf, tmp_path / "office") == pdf


def test_rejects_unknown_office_type(tmp_path: Path) -> None:
    src = tmp_path / "notes.txt"
    src.write_text("hi", encoding="utf-8")
    try:
        convert_office_to_pdf(src, tmp_path / "office", allowed=WORD_SUFFIXES | {".pdf"})
    except RuntimeError as exc:
        assert "notes.txt" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_large_office_files_get_longer_convert_timeout(tmp_path: Path) -> None:
    small = tmp_path / "small.pptx"
    small.write_bytes(b"x" * 1024)
    large = tmp_path / "large.pptm"
    large.write_bytes(b"x" * (50 * 1024 * 1024))
    assert _convert_timeout_seconds(small) == 600
    assert _convert_timeout_seconds(large) == 1800


def test_convert_reuses_existing_pdf(tmp_path: Path) -> None:
    src = tmp_path / "deck.pptx"
    src.write_bytes(b"pptx")
    office = tmp_path / "office"
    office.mkdir()
    existing = office / "deck.pdf"
    existing.write_bytes(b"%PDF-1.4\n")
    assert convert_office_to_pdf(src, office) == existing
