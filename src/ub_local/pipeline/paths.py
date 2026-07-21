from __future__ import annotations

from pathlib import Path

CHUNKS_EMBEDDED_FILENAME = "chunks_embedded.jsonl.gz"
CHUNKS_EMBEDDED_SHARD_PREFIX = "chunks_embedded-"
CHUNKS_EMBEDDED_SHARD_SUFFIX = ".jsonl.gz"
CORPUS_FILENAME = "corpus.json"
IMPORT_MANIFEST_FILENAME = "import.manifest.json"
EMBEDDING_MANIFEST_FILENAME = "embedding_manifest.json"


def embedded_shard_filename(index: int) -> str:
    return f"{CHUNKS_EMBEDDED_SHARD_PREFIX}{index:03d}{CHUNKS_EMBEDDED_SHARD_SUFFIX}"


def require_path(path: Path | str, label: str = "file") -> Path:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{label} not found: {p}")
    return p
