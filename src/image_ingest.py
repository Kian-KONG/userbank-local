from __future__ import annotations

import asyncio
import base64
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from .config import get_settings
from .deck_synth import first_title_line, synthesize_deck
from .office import DECK_SUFFIXES, convert_office_to_pdf as convert_office_file_to_pdf
from .pptx_outline import extract_pptx_slide_titles
from .rag import rag_describe_pages


def convert_office_to_pdf(input_path: Path, work: Path) -> Path:
    return convert_office_file_to_pdf(
        input_path, work, allowed=DECK_SUFFIXES | {".pdf"}
    )

__all__ = [
    "convert_office_to_pdf",
    "ingest_image_document",
    "render_pdf_pages",
]

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


def render_pdf_pages(pdf_path: Path, out_dir: Path, scale: float | None = None) -> list[Path]:
    s = get_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved_scale = scale if scale is not None else s.vision_page_scale
    proc = subprocess.run(
        [sys.executable, "-c", _RENDER_SCRIPT, str(pdf_path), str(out_dir), str(resolved_scale)],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        if "pypdfium2" in detail or "PIL" in detail or "Pillow" in detail:
            raise RuntimeError(
                "PPT page render needs pypdfium2 (+ Pillow) in the userbank-local venv "
                f"(make install). {detail}"
            )
        raise RuntimeError(f"Failed to render PDF pages: {detail}")
    pages = sorted(out_dir.glob("page_*.png"))
    if not pages:
        raise RuntimeError(f"No page PNGs under {out_dir}")
    return pages


def _page_number_from_name(path: Path) -> int:
    digits = "".join(ch for ch in path.stem if ch.isdigit())
    return int(digits) if digits else 0


def _vision_checkpoint_path(work: Path) -> Path:
    return work / "pages_vision.json"


def _load_vision_checkpoint(work: Path) -> dict[int, dict[str, Any]]:
    path = _vision_checkpoint_path(work)
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    pages = raw.get("pages") if isinstance(raw, dict) else raw
    out: dict[int, dict[str, Any]] = {}
    if not isinstance(pages, list):
        return out
    for page in pages:
        if not isinstance(page, dict):
            continue
        try:
            number = int(page.get("page_number") or 0)
        except (TypeError, ValueError):
            continue
        if number > 0 and str(page.get("description") or "").strip():
            out[number] = page
    return out


def _save_vision_checkpoint(work: Path, pages: list[dict[str, Any]]) -> None:
    _vision_checkpoint_path(work).write_text(
        json.dumps({"pages": pages}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


_MAX_VISION_CALLS_PER_PAGE = 12
_MAX_TILE_DEPTH = 1
_JPEG_MAX_SIDE = 1600
_REJECTED_REGION = (
    "[This region could not be described because the vision model repeatedly "
    "rejected the image.]"
)


class _VisionBudget:
    def __init__(self, limit: int = _MAX_VISION_CALLS_PER_PAGE) -> None:
        self.limit = limit
        self.used = 0

    def remaining(self) -> int:
        return max(0, self.limit - self.used)


def _is_retryable_vision(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "budget exhausted" in text:
        return False
    if "vision http 5" in text or "vision http 429" in text:
        return True
    return any(
        marker in text
        for marker in (
            "model request failed",
            "upstream proxy",
            "timed out",
            "timeout",
            "connecterror",
            "connection reset",
        )
    )


def _encode_jpeg(image: Image.Image, *, max_side: int = _JPEG_MAX_SIDE, quality: int = 80) -> bytes:
    width, height = image.size
    long_side = max(width, height)
    resized = image
    if long_side > max_side:
        scale = max_side / long_side
        resized = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )
    encoded = io.BytesIO()
    resized.save(encoded, "JPEG", quality=quality, optimize=True)
    return encoded.getvalue()


async def _vision_describe(
    image_base64: str,
    page_number: int,
    budget: _VisionBudget,
    *,
    mime: str,
) -> str:
    if budget.remaining() <= 0:
        raise RuntimeError("Vision call budget exhausted")
    budget.used += 1
    return (
        await rag_describe_pages(
            [
                {
                    "page_number": page_number,
                    "image_base64": image_base64,
                    "image_mime": mime,
                }
            ]
        )
    )[0]


async def _describe_page(png: Path, page_number: int) -> str:
    budget = _VisionBudget()
    png_b64 = base64.b64encode(png.read_bytes()).decode("ascii")
    for attempt in range(2):
        try:
            return await _vision_describe(
                png_b64, page_number, budget, mime="image/png"
            )
        except RuntimeError as exc:
            if not _is_retryable_vision(exc):
                raise
            if attempt == 0:
                await asyncio.sleep(1.5)

    with Image.open(png) as source:
        image = source.convert("RGB")
    jpeg_b64 = base64.b64encode(_encode_jpeg(image)).decode("ascii")
    try:
        return await _vision_describe(
            jpeg_b64, page_number, budget, mime="image/jpeg"
        )
    except RuntimeError as exc:
        if not _is_retryable_vision(exc) and "budget exhausted" not in str(exc):
            raise

    parts = await _describe_tiles(image, page_number, budget)
    return "\n\n".join(parts) if parts else _REJECTED_REGION


async def _describe_tiles(
    image: Image.Image,
    page_number: int,
    budget: _VisionBudget,
    *,
    depth: int = 0,
    label: str = "page",
) -> list[str]:
    width, height = image.size
    midpoint_x, midpoint_y = width // 2, height // 2
    tiles = [
        ("top-left", (0, 0, midpoint_x, midpoint_y)),
        ("top-right", (midpoint_x, 0, width, midpoint_y)),
        ("bottom-left", (0, midpoint_y, midpoint_x, height)),
        ("bottom-right", (midpoint_x, midpoint_y, width, height)),
    ]
    descriptions: list[str] = []
    for position, box in tiles:
        tile = image.crop(box)
        heading = f"### Vision tile: {label}/{position}"
        if budget.remaining() <= 0 or min(tile.size) < 128:
            descriptions.append(f"{heading}\n\n{_REJECTED_REGION}")
            continue
        encoded = _encode_jpeg(tile, max_side=max(tile.size), quality=85)
        try:
            description = await _vision_describe(
                base64.b64encode(encoded).decode("ascii"),
                page_number,
                budget,
                mime="image/jpeg",
            )
        except RuntimeError as exc:
            if not _is_retryable_vision(exc) and "budget exhausted" not in str(exc):
                raise
            if depth >= _MAX_TILE_DEPTH or budget.remaining() <= 0:
                descriptions.append(f"{heading}\n\n{_REJECTED_REGION}")
                continue
            descriptions.extend(
                await _describe_tiles(
                    tile,
                    page_number,
                    budget,
                    depth=depth + 1,
                    label=f"{label}/{position}",
                )
            )
        else:
            descriptions.append(f"{heading}\n\n{description}")
    return descriptions


async def ingest_image_document(
    input_path: Path,
    work: Path,
    on_progress: Any | None = None,
) -> Path:
    """PDF/PPT → per-page qwen3.8-max vision → deck synthesis → corpus JSON."""
    work = work.expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    input_path = input_path.expanduser().resolve()
    native_titles = extract_pptx_slide_titles(input_path)
    pdf_path = convert_office_to_pdf(input_path, work / "office")
    page_dir = work / "pages"
    pngs = sorted(page_dir.glob("page_*.png"))
    if not pngs:
        pngs = render_pdf_pages(pdf_path, page_dir)

    cached = _load_vision_checkpoint(work)
    pages_by_number: dict[int, dict[str, Any]] = {}
    pending: list[tuple[int, Path]] = []
    total = len(pngs)
    for index, png in enumerate(pngs, start=1):
        page_number = _page_number_from_name(png) or index
        existing = cached.get(page_number)
        if existing is not None:
            pages_by_number[page_number] = {
                "page_number": page_number,
                "title": existing.get("title") or native_titles.get(page_number) or "",
                "description": existing["description"],
            }
            print(f"==> skip vision page {page_number}/{total}")
        else:
            pending.append((page_number, png))

    lock = asyncio.Lock()

    def _ordered_pages() -> list[dict[str, Any]]:
        return [pages_by_number[n] for n in sorted(pages_by_number)]

    async def _flush(done: int) -> None:
        _save_vision_checkpoint(work, _ordered_pages())
        if on_progress is not None:
            maybe = on_progress("vision", done, total)
            if hasattr(maybe, "__await__"):
                await maybe

    await _flush(len(pages_by_number))
    workers = max(1, int(get_settings().vision_concurrency or 1))
    if pending:
        print(f"==> vision concurrency {min(workers, len(pending))} remaining={len(pending)}")
    sem = asyncio.Semaphore(workers)

    async def _one(page_number: int, png: Path) -> None:
        async with sem:
            try:
                description = await _describe_page(png, page_number)
            except Exception as exc:  # noqa: BLE001
                print(f"==> vision page {page_number}/{total} failed: {exc}")
                description = f"{_REJECTED_REGION}\n\n({exc})"
        title = native_titles.get(page_number) or first_title_line(description)
        async with lock:
            pages_by_number[page_number] = {
                "page_number": page_number,
                "title": title,
                "description": description,
            }
            done = len(pages_by_number)
            await _flush(done)
        print(f"==> vision page {page_number}/{total}")

    if pending:
        await asyncio.gather(*[_one(number, png) for number, png in pending])

    pages = _ordered_pages()

    try:
        synth = await synthesize_deck(pages)
    except Exception as exc:  # noqa: BLE001
        print(f"==> deck synth skipped: {type(exc).__name__}: {exc}")
        synth = {"argument": "", "outline": [], "pages": []}
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
