from __future__ import annotations

import re
from pathlib import Path

SLIDE_APP = re.compile(
    r"(powerpoint|impress|keynote|google slides)",
    re.I,
)

# ISO / US office paper in PDF points (1/72 in). Landscape or portrait.
_OFFICE_PAPER = (
    (595, 842),  # A4
    (612, 792),  # Letter
    (612, 1008),  # Legal
    (842, 1191),  # A3
)


def looks_like_deck_pdf(
    *,
    producer: str = "",
    creator: str = "",
    page_sizes: list[tuple[float, float]],
) -> bool:
    """True when a PDF is slide-shaped (Qwen vision), not a text report (MinerU)."""
    blob = f"{producer} {creator}"
    if SLIDE_APP.search(blob):
        return True
    if not page_sizes:
        return False
    slide_votes = 0
    for width, height in page_sizes:
        if _is_office_paper(width, height):
            continue
        long, short = (width, height) if width >= height else (height, width)
        if short <= 0:
            continue
        ratio = long / short
        landscape = width > height
        if landscape and 1.70 <= ratio <= 1.85:
            slide_votes += 1
        elif landscape and 1.30 <= ratio <= 1.38 and long >= 700:
            slide_votes += 1
    return slide_votes / len(page_sizes) >= 0.6


def pdf_is_deck(path: Path) -> bool:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return False
    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception:
        return False
    try:
        count = len(doc)
        sizes = [doc.get_page_size(i) for i in range(min(count, 8))]
        return looks_like_deck_pdf(
            producer=doc.get_metadata_value("Producer") or "",
            creator=doc.get_metadata_value("Creator") or "",
            page_sizes=sizes,
        )
    except Exception:
        return False
    finally:
        doc.close()


def _is_office_paper(width: float, height: float) -> bool:
    short, long = sorted((width, height))
    return any(
        abs(short - paper_w) < 18 and abs(long - paper_h) < 18
        for paper_w, paper_h in _OFFICE_PAPER
    )
