from __future__ import annotations

import json
import uuid
from pathlib import Path
from collections.abc import Callable
from typing import Any

from ub_local.config import get_settings
from ub_local.pipeline.embed_batch import embed_flat_chunks
from ub_local.pipeline.embedded_jsonl import write_embedded_jsonl_gz
from ub_local.pipeline.flatten_corpus import flatten_corpus
from ub_local.pipeline.manifest import build_import_manifest, write_import_manifest
from ub_local.pipeline.paths import (
    CHUNKS_EMBEDDED_FILENAME,
    CORPUS_FILENAME,
    EMBEDDING_MANIFEST_FILENAME,
    require_path,
)
from ub_local.pipeline.types import DEFAULT_EMBED_BATCH_SIZE, FlatChunk

ProgressCb = Callable[[int, int], None]


def export_knowledge_bundle(
    *,
    corpus_path: Path | str,
    output_dir: Path | str,
    document_id: str = "local-doc",
    org_id: str | None = None,
    job_id: str | None = None,
    batch_size: int = DEFAULT_EMBED_BATCH_SIZE,
    filename: str | None = None,
    log: Any = print,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    corpus_file = require_path(corpus_path, "corpus file")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    resolved_job = job_id or str(uuid.uuid4())
    resolved_org = org_id or settings.survey_org_id

    corpus = json.loads(corpus_file.read_text(encoding="utf-8"))
    flat_chunks = flatten_corpus(corpus, document_id)
    if not flat_chunks:
        raise RuntimeError("corpus produced no embeddable paragraphs")

    corpus_copy = out / CORPUS_FILENAME
    corpus_copy.write_text(
        json.dumps(corpus, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    embedded_path = out / CHUNKS_EMBEDDED_FILENAME
    embedded_items = []
    batch: list[FlatChunk] = []
    total = 0
    for chunk in flat_chunks:
        batch.append(chunk)
        if len(batch) < batch_size:
            continue
        embedded = embed_flat_chunks(batch)
        for item in embedded:
            total += 1
            log(f"embedded {total}/{len(flat_chunks)}")
            if on_progress:
                on_progress(total, len(flat_chunks))
            embedded_items.append(item)
        batch = []
    if batch:
        embedded = embed_flat_chunks(batch)
        for item in embedded:
            total += 1
            log(f"embedded {total}/{len(flat_chunks)}")
            if on_progress:
                on_progress(total, len(flat_chunks))
            embedded_items.append(item)

    chunk_count = write_embedded_jsonl_gz(embedded_path, embedded_items)

    embedding_manifest = {
        "embedding_model": settings.embedding_model,
        "dimensions": settings.vector_store_dimension,
        "chunk_count": chunk_count,
        "document_id": document_id,
        "source_corpus": str(corpus_file),
        "corpus_file": str(corpus_copy),
        "embedded_file": str(embedded_path),
    }
    manifest_path = out / EMBEDDING_MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(embedding_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    import_manifest = build_import_manifest(
        job_id=resolved_job,
        bundle_type="knowledge",
        org_id=resolved_org,
        bundle_dir=out,
        chunk_count=chunk_count,
        filename=filename or f"{document_id}.pdf",
        document_id=document_id,
        include_corpus=True,
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
