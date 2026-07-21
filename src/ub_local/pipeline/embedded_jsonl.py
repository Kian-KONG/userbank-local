from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from ub_local.pipeline.types import EmbeddedChunk


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def build_staging_file_entry(path: Path) -> dict[str, Any]:
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def iter_embedded_jsonl_gz(path: Path) -> Iterator[EmbeddedChunk]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def write_embedded_jsonl_gz(path: Path, chunks: Iterable[EmbeddedChunk]) -> int:
    total = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False))
            f.write(chr(10))
            total += 1
    return total
