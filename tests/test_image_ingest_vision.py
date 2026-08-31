import asyncio
import base64
import io
from pathlib import Path

from PIL import Image

from src.image_ingest import (
    _describe_page,
    _is_retryable_vision,
    _load_vision_checkpoint,
    _save_vision_checkpoint,
    ingest_image_document,
)


def _png_bytes(size: tuple[int, int] = (400, 300)) -> bytes:
    image = Image.new("RGB", size, (40, 80, 120))
    for y in range(0, size[1], 8):
        for x in range(0, size[0], 8):
            image.putpixel((x, y), ((x * 3) % 256, (y * 5) % 256, 90))
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def _write_png(path: Path, size: tuple[int, int] = (400, 300)) -> Path:
    path.write_bytes(_png_bytes(size))
    return path


def _vision_502(page_number: int = 1) -> RuntimeError:
    return RuntimeError(
        f'Vision HTTP 502 page {page_number}: {{"detail":"Vision API HTTP 502: model request failed"}}'
    )


def test_is_retryable_vision_requires_502_and_model_failed():
    assert _is_retryable_vision(_vision_502())
    assert _is_retryable_vision(
        RuntimeError(
            'Vision HTTP 502 page 43: {"detail":"503 Fail to connect with upstream proxy rb-proxy-szh.bosch.com:8080"}'
        )
    )
    assert not _is_retryable_vision(RuntimeError("Vision HTTP 401 page 1: unauthorized"))
    assert not _is_retryable_vision(RuntimeError("Vision call budget exhausted"))


def test_describe_page_retries_once_before_downsample(tmp_path: Path, monkeypatch):
    png = _write_png(tmp_path / "page_001.png")
    calls: list[str] = []

    async def fake_describe(pages):
        mime = pages[0].get("image_mime")
        calls.append(mime)
        if len(calls) == 1:
            raise _vision_502()
        return ["ok after retry"]

    monkeypatch.setattr("src.image_ingest.rag_describe_pages", fake_describe)
    assert asyncio.run(_describe_page(png, 1)) == "ok after retry"
    assert calls == ["image/png", "image/png"]


def test_describe_page_downsamples_to_jpeg_before_tiles(tmp_path: Path, monkeypatch):
    png = _write_png(tmp_path / "page_001.png", (2000, 1200))
    calls: list[dict] = []

    async def fake_describe(pages):
        page = pages[0]
        calls.append(page)
        if page.get("image_mime") == "image/png":
            raise _vision_502()
        return ["jpeg page"]

    monkeypatch.setattr("src.image_ingest.rag_describe_pages", fake_describe)
    assert asyncio.run(_describe_page(png, 4)) == "jpeg page"
    assert [c.get("image_mime") for c in calls] == ["image/png", "image/png", "image/jpeg"]
    jpeg_raw = base64.b64decode(calls[-1]["image_base64"])
    assert jpeg_raw.startswith(b"\xff\xd8\xff")


def test_describe_page_stops_at_call_budget(tmp_path: Path, monkeypatch):
    png = _write_png(tmp_path / "page_001.png", (800, 600))
    calls = {"n": 0}

    async def fake_describe(pages):
        calls["n"] += 1
        raise _vision_502()

    monkeypatch.setattr("src.image_ingest.rag_describe_pages", fake_describe)
    text = asyncio.run(_describe_page(png, 1))
    assert "could not be described" in text
    assert calls["n"] <= 12
    assert calls["n"] >= 3


def test_ingest_skips_checkpointed_pages(tmp_path: Path, monkeypatch):
    work = tmp_path / "parse"
    pages_dir = work / "pages"
    pages_dir.mkdir(parents=True)
    _write_png(pages_dir / "page_001.png")
    _write_png(pages_dir / "page_002.png")
    _save_vision_checkpoint(
        work,
        [{"page_number": 1, "title": "Cover", "description": "cached cover"}],
    )
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    vision_calls: list[int] = []

    async def fake_describe(pages):
        vision_calls.append(int(pages[0]["page_number"]))
        return [f"live page {pages[0]['page_number']}"]

    async def fake_synth(pages):
        return {"argument": "thesis", "outline": [], "pages": []}

    monkeypatch.setattr("src.image_ingest.extract_pptx_slide_titles", lambda path: {})
    monkeypatch.setattr("src.image_ingest.convert_office_to_pdf", lambda path, dest: pdf)
    monkeypatch.setattr("src.image_ingest.rag_describe_pages", fake_describe)
    monkeypatch.setattr("src.image_ingest.synthesize_deck", fake_synth)

    corpus = asyncio.run(ingest_image_document(pdf, work))
    data = corpus.read_text(encoding="utf-8")
    assert "cached cover" in data
    assert "live page 2" in data
    assert vision_calls == [2]
    cached = _load_vision_checkpoint(work)
    assert 1 in cached and 2 in cached


def test_ingest_describes_pending_pages_concurrently(tmp_path: Path, monkeypatch):
    work = tmp_path / "parse"
    pages_dir = work / "pages"
    pages_dir.mkdir(parents=True)
    for n in range(1, 5):
        _write_png(pages_dir / f"page_{n:03d}.png")
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    inflight = 0
    max_inflight = 0

    async def fake_describe(pages):
        nonlocal inflight, max_inflight
        inflight += 1
        max_inflight = max(max_inflight, inflight)
        await asyncio.sleep(0.05)
        inflight -= 1
        return [f"live page {pages[0]['page_number']}"]

    async def fake_synth(pages):
        return {"argument": "thesis", "outline": [], "pages": []}

    monkeypatch.setattr("src.image_ingest.extract_pptx_slide_titles", lambda path: {})
    monkeypatch.setattr("src.image_ingest.convert_office_to_pdf", lambda path, dest: pdf)
    monkeypatch.setattr("src.image_ingest.rag_describe_pages", fake_describe)
    monkeypatch.setattr("src.image_ingest.synthesize_deck", fake_synth)
    monkeypatch.setattr(
        "src.image_ingest.get_settings",
        lambda: type("S", (), {"vision_concurrency": 4})(),
    )

    asyncio.run(ingest_image_document(pdf, work))
    assert max_inflight >= 3
    cached = _load_vision_checkpoint(work)
    assert set(cached) == {1, 2, 3, 4}


def test_ingest_keeps_going_when_one_page_is_not_retryable(tmp_path: Path, monkeypatch):
    work = tmp_path / "parse"
    pages_dir = work / "pages"
    pages_dir.mkdir(parents=True)
    for n in range(1, 4):
        _write_png(pages_dir / f"page_{n:03d}.png")
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    async def fake_describe(pages):
        number = int(pages[0]["page_number"])
        if number == 2:
            raise RuntimeError("Vision HTTP 401 page 2: unauthorized")
        return [f"live page {number}"]

    async def fake_synth(pages):
        return {"argument": "thesis", "outline": [], "pages": []}

    monkeypatch.setattr("src.image_ingest.extract_pptx_slide_titles", lambda path: {})
    monkeypatch.setattr("src.image_ingest.convert_office_to_pdf", lambda path, dest: pdf)
    monkeypatch.setattr("src.image_ingest.rag_describe_pages", fake_describe)
    monkeypatch.setattr("src.image_ingest.synthesize_deck", fake_synth)
    monkeypatch.setattr(
        "src.image_ingest.get_settings",
        lambda: type("S", (), {"vision_concurrency": 3})(),
    )

    asyncio.run(ingest_image_document(pdf, work))
    cached = _load_vision_checkpoint(work)
    assert "live page 1" in cached[1]["description"]
    assert "could not be described" in cached[2]["description"]
    assert "live page 3" in cached[3]["description"]
