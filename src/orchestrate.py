from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import get_settings, path_exists


def check_mineru() -> dict:
    p = get_settings().mineru_path()
    return {"ok": path_exists(p), "path": str(p)}


def check_deepread() -> dict:
    p = get_settings().deepread_path()
    return {"ok": path_exists(p), "path": str(p)}


def parse_document(input_path: Path, work: Path, skip_mineru: bool = False) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    name = input_path.name

    if name.endswith("_corpus.json") or name.endswith(".corpus.json"):
        dest = work / "doc_corpus.json"
        dest.write_bytes(input_path.read_bytes())
        return dest

    if name.endswith((".md", ".markdown", ".txt")):
        text = input_path.read_text(encoding="utf-8")
        corpus = markdown_to_corpus(name, text)
        dest = work / "doc_corpus.json"
        dest.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return dest

    if name.endswith(".json"):
        dest = work / "doc_corpus.json"
        dest.write_bytes(input_path.read_bytes())
        return dest

    s = get_settings()
    deepread = s.deepread_path()
    if path_exists(deepread) and not skip_mineru:
        out = work / "deepread_out"
        out.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [s.mineru_python, "-m", "deepread", str(input_path), "--out", str(out)],
            cwd=str(deepread),
            check=False,
        )
        if proc.returncode == 0:
            found = find_corpus(out)
            if found is not None:
                dest = work / "doc_corpus.json"
                dest.write_bytes(found.read_bytes())
                return dest

    raise RuntimeError(
        f"Cannot parse {input_path}: provide *_corpus.json / markdown, "
        "or install DeepRead/MinerU siblings"
    )


def markdown_to_corpus(filename: str, text: str) -> dict:
    paragraphs = [
        {"content": p.strip()}
        for p in text.split("\n\n")
        if p.strip()
    ]
    return {
        "filename": filename,
        "nodes": [
            {
                "id": "root",
                "title": filename,
                "paragraphs": paragraphs,
            }
        ],
    }


def find_corpus(directory: Path) -> Path | None:
    for path in directory.rglob("*.json"):
        if "corpus" in path.name:
            return path
    return None
