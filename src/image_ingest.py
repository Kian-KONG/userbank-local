from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import get_settings
from .deck_synth import first_title_line, synthesize_deck
from .pptx_outline import extract_pptx_slide_titles
from .rag import rag_describe_pages

_RENDER_SCRIPT = """
import sys
from pathlib import Path
import pypdfium2 as pdfium

pdf_path, out_dir, scale_s = sys.argv[1], sys.argv[2], sys.argv[3]
scale = float(scale_s)
out = Path(out_dir)
out.mkdir(parents=True, exist_ok=True)
doc = pdfium.PdfDocument(pdf_path)
count = len(doc)
for index in range(count):
    page = doc[index]
    bitmap = page.render(scale=scale)
    image = bitmap.to_pil()
    dest = out / f"page_{index + 1:03d}.png"
    image.save(dest, "PNG")
    page.close()
doc.close()
print(count)
"""


def convert_office_to_pdf(input_path: Path, work: Path) -> Path:
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        return input_path
    if suffix not in {".ppt", ".pptx"}:
        raise RuntimeError(f"Image track requires PDF or PPT/PPTX, got {input_path.name}")
    soffice = shutil.which("soffice") or shutil.which("soffice.bin")
    if not soffice:
        raise RuntimeError(
            "PPT/PPTX needs LibreOffice (`soffice`) on PATH, or export the deck to PDF first"
        )
    work.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(work),
            str(input_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"LibreOffice convert failed: {detail}")
    converted = work / f"{input_path.stem}.pdf"
    if not converted.exists():
        matches = sorted(work.glob("*.pdf"))
        if not matches:
            raise RuntimeError(f"LibreOffice produced no PDF under {work}")
        converted = matches[0]
    return converted


def render_pdf_pages(pdf_path: Path, out_dir: Path, scale: float | None = None) -> list[Path]:
    s = get_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    py = s.resolved_mineru_python()
    resolved_scale = scale if scale is not None else s.vision_page_scale
    proc = subprocess.run(
        [py, "-c", _RENDER_SCRIPT, str(pdf_path), str(out_dir), str(resolved_scale)],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to render PDF pages: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    pages = sorted(out_dir.glob("page_*.png"))
    if not pages:
        raise RuntimeError(f"No page PNGs under {out_dir}")
    return pages


def _page_number_from_name(path: Path) -> int:
    digits = "".join(ch for ch in path.stem if ch.isdigit())
    return int(digits) if digits else 0


async def ingest_image_document(
    input_path: Path,
    work: Path,
    on_progress: Any | None = None,
) -> Path:
    """PDF/PPT → per-page Plus vision → Max deck synthesis → corpus JSON."""
    work = work.expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    input_path = input_path.expanduser().resolve()
    native_titles = extract_pptx_slide_titles(input_path)
    pdf_path = convert_office_to_pdf(input_path, work / "office")
    pngs = render_pdf_pages(pdf_path, work / "pages")

    pages: list[dict[str, Any]] = []
    total = len(pngs)
    for index, png in enumerate(pngs, start=1):
        page_number = _page_number_from_name(png) or index
        image_base64 = base64.b64encode(png.read_bytes()).decode("ascii")
        descriptions = await rag_describe_pages(
            [{"page_number": page_number, "image_base64": image_base64}]
        )
        description = descriptions[0]
        title = native_titles.get(page_number) or first_title_line(description)
        pages.append(
            {
                "page_number": page_number,
                "title": title,
                "description": description,
            }
        )
        if on_progress is not None:
            maybe = on_progress("vision", index, total)
            if hasattr(maybe, "__await__"):
                await maybe

    synth = await synthesize_deck(pages)
    by_page = {int(entry["page"]): entry for entry in synth.get("pages") or []}
    merged_pages: list[dict[str, Any]] = []
    for page in pages:
        extra = by_page.get(int(page["page_number"])) or {}
        merged_pages.append(
            {
                **page,
                "section": extra.get("section") or "",
                "role": extra.get("role") or "evidence",
                "continues": extra.get("continues"),
                "refers_to": extra.get("refers_to") or [],
            }
        )

    corpus = {
        "filename": input_path.name,
        "source_type": "image",
        "overview": {
            "argument": synth.get("argument") or "",
            "outline": synth.get("outline") or [],
        },
        "pages": merged_pages,
    }
    dest = work / "doc_corpus.json"
    dest.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest
