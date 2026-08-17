from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_PIPE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_PIPE_ALIGN = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$")
_HTML_IMG = re.compile(r"<img\s+[^>]*src=[\"']([^\"']+)[\"'][^>]*", re.IGNORECASE)
_MD_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def parse_markdown_to_corpus(
    text: str,
    *,
    filename: str,
    md_dir: Path | None = None,
) -> dict[str, Any]:
    """Turn MinerU markdown into the node/paragraph corpus flatten_for_export expects.

    Headings become sibling nodes (no parent/child tree). HTML and pipe tables
    stay one paragraph so numbers are not split across chunks.
    """
    lines = text.splitlines()
    nodes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    buf: list[str] = []
    next_id = 1

    def flush_text() -> None:
        nonlocal buf
        block = "\n".join(buf).strip()
        buf = []
        if not block:
            return
        _ensure_node()["paragraphs"].append(block)

    def _ensure_node() -> dict[str, Any]:
        nonlocal current, next_id
        if current is None:
            current = {
                "id": str(next_id),
                "title": "前言",
                "paragraphs": [],
                "children": [],
            }
            next_id += 1
            nodes.append(current)
        return current

    def new_node(title: str) -> None:
        nonlocal current, next_id
        flush_text()
        current = {
            "id": str(next_id),
            "title": title.strip(),
            "paragraphs": [],
            "children": [],
        }
        next_id += 1
        nodes.append(current)

    i = 0
    while i < len(lines):
        line = lines[i]
        heading = _HEADING.match(line)
        if heading:
            new_node(heading.group(2))
            i += 1
            continue

        if "<table" in line.lower():
            flush_text()
            block, i = _extract_html_table(lines, i)
            _ensure_node()["paragraphs"].append(block)
            continue

        if _PIPE_ROW.match(line) or _PIPE_ALIGN.match(line):
            flush_text()
            block, i = _extract_md_table(lines, i)
            _ensure_node()["paragraphs"].append(block)
            continue

        image = _extract_image(line, md_dir)
        if image is not None:
            flush_text()
            _ensure_node()["paragraphs"].append(image)
            i += 1
            continue

        if not line.strip():
            flush_text()
            i += 1
            continue

        buf.append(line)
        i += 1

    flush_text()
    if not nodes:
        nodes.append(
            {
                "id": "1",
                "title": filename,
                "paragraphs": [],
                "children": [],
            }
        )
    return {"filename": filename, "nodes": nodes}


def write_corpus(md_path: Path, work: Path) -> Path:
    md_path = md_path.expanduser().resolve()
    work = work.expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    text = md_path.read_text(encoding="utf-8")
    corpus = parse_markdown_to_corpus(
        text, filename=md_path.name, md_dir=md_path.parent
    )
    dest = work / "doc_corpus.json"
    dest.write_text(
        json.dumps(corpus, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_copy = work / "doc.md"
    if md_path.resolve() != md_copy.resolve():
        md_copy.write_text(text, encoding="utf-8")
    print(f"==> Corpus: {dest} ({len(corpus['nodes'])} nodes)")
    return dest


def _extract_html_table(lines: list[str], start: int) -> tuple[str, int]:
    buf = [lines[start]]
    i = start + 1
    if "</table>" in lines[start].lower():
        return "\n".join(buf), i
    while i < len(lines):
        buf.append(lines[i])
        if "</table>" in lines[i].lower():
            i += 1
            break
        i += 1
    return "\n".join(buf), i


def _extract_md_table(lines: list[str], start: int) -> tuple[str, int]:
    buf: list[str] = []
    i = start
    while i < len(lines) and (_PIPE_ROW.match(lines[i]) or _PIPE_ALIGN.match(lines[i])):
        buf.append(lines[i])
        i += 1
    return "\n".join(buf), i


def _extract_image(line: str, md_dir: Path | None) -> dict[str, Any] | None:
    html = _HTML_IMG.search(line)
    if html:
        src = html.group(1).strip()
        alt_m = re.search(r"alt=[\"']([^\"']+)[\"']", line, re.IGNORECASE)
        alt = alt_m.group(1).strip() if alt_m else ""
        return {"type": "image", "content": alt, "image_path": _resolve_src(src, md_dir)}

    md = _MD_IMG.search(line)
    if md:
        return {
            "type": "image",
            "content": md.group(1).strip(),
            "image_path": _resolve_src(md.group(2).strip(), md_dir),
        }
    return None


def _resolve_src(src: str, md_dir: Path | None) -> str:
    if src.startswith(("http://", "https://", "data:")) or md_dir is None:
        return src
    return os.path.normpath(str(md_dir / src))
