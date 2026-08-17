from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .config import get_settings, path_exists
from .markdown_corpus import write_corpus

HTTP_CLIENT_BACKENDS = {"vlm-http-client", "hybrid-http-client"}


def check_mineru() -> dict:
    p = get_settings().mineru_path()
    return {"ok": path_exists(p), "path": str(p)}


def parse_document(
    input_path: Path,
    work: Path,
    skip_mineru: bool = False,
    formula: bool | None = None,
    table: bool | None = None,
) -> Path:
    """PDF → MinerU markdown → local corpus JSON."""
    work = work.expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    input_path = input_path.expanduser().resolve()
    name = input_path.name

    if name.endswith("_corpus.json") or name.endswith(".corpus.json"):
        dest = work / "doc_corpus.json"
        dest.write_bytes(input_path.read_bytes())
        return dest

    if name.endswith((".md", ".markdown", ".txt")):
        return write_corpus(input_path, work)

    if name.endswith(".json"):
        dest = work / "doc_corpus.json"
        dest.write_bytes(input_path.read_bytes())
        return dest

    if not name.lower().endswith(".pdf"):
        raise RuntimeError(
            f"Cannot parse {input_path}: provide PDF / markdown / *_corpus.json"
        )

    if skip_mineru:
        raise RuntimeError("--skip-mineru requires markdown or corpus input")

    md_path = _mineru_pdf_to_markdown(
        input_path, work / "mineru_out", formula=formula, table=table
    )
    return write_corpus(md_path, work)


def _mineru_env() -> dict[str, str]:
    s = get_settings()
    env = os.environ.copy()
    env["MINERU_MODEL_SOURCE"] = s.mineru_model_source or "local"
    env["MINERU_TASK_RESULT_TIMEOUT_SECONDS"] = str(
        int(s.mineru_task_timeout_seconds)
    )
    env.setdefault("HF_HUB_OFFLINE", "1")
    env.setdefault("TRANSFORMERS_OFFLINE", "1")
    env.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = "127.0.0.1,localhost"
    return env


def _pdf_page_count(pdf_path: Path, py: str) -> int:
    script = (
        "import sys; import pypdfium2 as pdfium; "
        "doc = pdfium.PdfDocument(sys.argv[1]); n = len(doc); doc.close(); print(n)"
    )
    proc = subprocess.run(
        [py, "-c", script, str(pdf_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to read PDF page count: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return int(proc.stdout.strip())


def _page_chunks(page_count: int, chunk_size: int) -> list[tuple[int, int]]:
    size = max(1, int(chunk_size))
    chunks: list[tuple[int, int]] = []
    start = 0
    while start < page_count:
        end = min(start + size - 1, page_count - 1)
        chunks.append((start, end))
        start = end + 1
    return chunks


def _mineru_pdf_to_markdown(
    pdf_path: Path,
    out_dir: Path,
    formula: bool | None = None,
    table: bool | None = None,
) -> Path:
    s = get_settings()
    mineru_root = s.mineru_path()
    if not path_exists(mineru_root):
        raise RuntimeError(f"MinerU not found at {mineru_root}")

    use_formula = s.mineru_formula if formula is None else formula
    use_table = s.mineru_table if table is None else table
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    py = s.resolved_mineru_python()
    page_count = _pdf_page_count(pdf_path, py)
    chunks = _page_chunks(page_count, s.mineru_page_chunk_size)
    print(
        f"==> MinerU: {page_count} pages, {len(chunks)} chunk(s) "
        f"(size={s.mineru_page_chunk_size}, backend={s.mineru_backend}"
        f"{', effort=' + s.mineru_effort if s.mineru_backend.startswith('hybrid') else ''}"
        f", formula={str(use_formula).lower()}, table={str(use_table).lower()})"
    )

    md_parts: list[tuple[int, int, Path]] = []
    for index, (start, end) in enumerate(chunks, start=1):
        chunk_dir = out_dir / f"chunk_{start:04d}-{end:04d}"
        marker = chunk_dir / ".ok"
        if marker.exists():
            md = find_markdown(chunk_dir)
            if md is not None:
                print(f"==> skip chunk {index}/{len(chunks)} pages {start}-{end}: {md}")
                md_parts.append((start, end, md))
                continue
        print(f"==> chunk {index}/{len(chunks)} pages {start}-{end}")
        _run_mineru_chunk(
            pdf_path,
            chunk_dir,
            start,
            end,
            mineru_root,
            py,
            formula=use_formula,
            table=use_table,
        )
        md = find_markdown(chunk_dir)
        if md is None:
            raise RuntimeError(f"MinerU produced no markdown under {chunk_dir}")
        marker.write_text(str(md), encoding="utf-8")
        print(f"==> chunk done: {md}")
        md_parts.append((start, end, md))

    merged = _merge_chunk_markdown(out_dir / "merged.md", md_parts)
    print(f"==> MinerU markdown: {merged}")
    return merged


def _mineru_client_cmd(
    *,
    py: str,
    pdf_path: Path,
    chunk_dir: Path,
    start: int,
    end: int,
    backend: str,
    formula: bool,
    table: bool,
    effort: str,
    api_url: str,
) -> list[str]:
    cmd = [
        py,
        "-m",
        "mineru.cli.client",
        "-p",
        str(pdf_path),
        "-o",
        str(chunk_dir),
        "-b",
        backend,
        "-s",
        str(start),
        "-e",
        str(end),
        "-f",
        "true" if formula else "false",
        "-t",
        "true" if table else "false",
    ]
    if backend.startswith("hybrid"):
        effort = (effort or "high").strip()
        cmd.extend(["--effort", effort])
        if effort == "high":
            cmd.extend(["--image-analysis", "true"])
    if api_url:
        cmd.extend(["--api-url", api_url])
    elif backend in HTTP_CLIENT_BACKENDS:
        raise RuntimeError(f"{backend} requires MINERU_API_URL")
    return cmd


def _run_mineru_chunk(
    pdf_path: Path,
    chunk_dir: Path,
    start: int,
    end: int,
    mineru_root: Path,
    py: str,
    formula: bool = True,
    table: bool = True,
) -> None:
    s = get_settings()
    chunk_dir = chunk_dir.expanduser().resolve()
    chunk_dir.mkdir(parents=True, exist_ok=True)
    backend = (s.mineru_backend or "vlm-engine").strip()
    cmd = _mineru_client_cmd(
        py=py,
        pdf_path=pdf_path,
        chunk_dir=chunk_dir,
        start=start,
        end=end,
        backend=backend,
        formula=formula,
        table=table,
        effort=s.mineru_effort,
        api_url=s.mineru_api_url.strip(),
    )
    env = _mineru_env()
    timeout = max(60.0, float(s.mineru_task_timeout_seconds))
    print(f"==> MinerU: {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=str(mineru_root),
        env=env,
        check=False,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"MinerU chunk pages {start}-{end} failed with exit code {proc.returncode}"
        )


def _merge_chunk_markdown(
    dest: Path, parts: list[tuple[int, int, Path]]
) -> Path:
    blocks: list[str] = []
    for start, end, md_path in parts:
        text = md_path.read_text(encoding="utf-8")
        rel = Path(os.path.relpath(md_path.parent, dest.parent)).as_posix()
        text = text.replace("](./images/", f"]({rel}/images/")
        text = text.replace("](images/", f"]({rel}/images/")
        blocks.append(f"<!-- mineru pages {start}-{end} -->\n\n{text.strip()}\n")
    dest.write_text("\n".join(blocks).rstrip() + "\n", encoding="utf-8")
    return dest


def find_markdown(directory: Path) -> Path | None:
    preferred: list[Path] = []
    others: list[Path] = []
    for path in directory.rglob("*.md"):
        if path.name in {"merged.md"}:
            continue
        if path.name.endswith("_origin.md"):
            continue
        normalized = str(path).replace("\\", "/")
        parent = path.parent.name
        if (
            "/vlm/" in normalized
            or "/hybrid_" in normalized
            or "/hybrid/" in normalized
            or parent in {"vlm", "hybrid", "pipeline", "auto"}
            or parent.startswith("hybrid_")
        ):
            preferred.append(path)
        else:
            others.append(path)
    if preferred:
        return sorted(preferred, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    if others:
        return sorted(others, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    return None
