from __future__ import annotations

import gzip
import json
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from ub_local.config import get_settings
from ub_local.pipeline.embed_batch import embed_flat_chunks
from ub_local.pipeline.embedded_jsonl import write_embedded_jsonl_gz
from ub_local.pipeline.manifest import build_import_manifest, write_import_manifest
from ub_local.pipeline.paths import (
    CHUNKS_EMBEDDED_FILENAME,
    EMBEDDING_MANIFEST_FILENAME,
    require_path,
)
from ub_local.pipeline.types import DEFAULT_EMBED_BATCH_SIZE, FlatChunk

ProgressCb = Callable[[int, int], None]


def _iter_flat_jsonl_gz(path: Path) -> Iterator[FlatChunk]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parsed = json.loads(line)
            text = str(parsed.get("text") or "").strip()
            if not text:
                continue
            yield {
                "id": str(parsed.get("id") or uuid.uuid4()),
                "text": text,
                "metadata": dict(parsed.get("metadata") or {}),
            }


def _count_chunks(path: Path) -> int:
    return sum(1 for _ in _iter_flat_jsonl_gz(path))


def embed_seed_bundle(
    *,
    chunks_path: Path | str,
    output_dir: Path | str,
    org_id: str | None = None,
    job_id: str | None = None,
    persona_id: str | None = None,
    batch_size: int = DEFAULT_EMBED_BATCH_SIZE,
    log: Any = print,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Embed pre-built survey flat chunks (jsonl.gz) into an uploadable bundle."""
    settings = get_settings()
    src = require_path(chunks_path, "chunks file")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    resolved_job = job_id or f"survey-{uuid.uuid4()}"
    resolved_org = org_id or settings.survey_org_id

    total_estimate = _count_chunks(src)
    if total_estimate == 0:
        raise RuntimeError("survey chunks file produced no embeddable rows")

    embedded_path = out / CHUNKS_EMBEDDED_FILENAME
    batch: list[FlatChunk] = []
    embedded_items = []
    done = 0

    for chunk in _iter_flat_jsonl_gz(src):
        batch.append(chunk)
        if len(batch) < batch_size:
            continue
        for item in embed_flat_chunks(batch):
            done += 1
            if done % batch_size == 0:
                log(f"embedded {done}/{total_estimate}")
            if on_progress:
                on_progress(done, total_estimate)
            embedded_items.append(item)
        batch = []
    if batch:
        for item in embed_flat_chunks(batch):
            done += 1
            log(f"embedded {done}/{total_estimate}")
            if on_progress:
                on_progress(done, total_estimate)
            embedded_items.append(item)

    chunk_count = write_embedded_jsonl_gz(embedded_path, embedded_items)

    embedding_manifest = {
        "embedding_model": settings.embedding_model,
        "dimensions": settings.vector_store_dimension,
        "chunk_count": chunk_count,
        "source": str(src),
        "output": str(embedded_path),
    }
    manifest_path = out / EMBEDDING_MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(embedding_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    import_manifest = build_import_manifest(
        job_id=resolved_job,
        bundle_type="survey",
        org_id=resolved_org,
        bundle_dir=out,
        chunk_count=chunk_count,
        persona_id=persona_id,
        include_corpus=False,
    )
    import_manifest_path = write_import_manifest(out, import_manifest)
    log(f"done: {chunk_count} chunks -> {embedded_path}")
    return {
        "output_dir": str(out),
        "embedded_path": str(embedded_path),
        "manifest_path": str(manifest_path),
        "import_manifest_path": str(import_manifest_path),
        "chunk_count": chunk_count,
        "job_id": resolved_job,
    }
