from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ub_local.config import get_settings
from ub_local.pipeline.embedded_jsonl import build_staging_file_entry
from ub_local.pipeline.paths import (
    CHUNKS_EMBEDDED_FILENAME,
    CORPUS_FILENAME,
    IMPORT_MANIFEST_FILENAME,
)
from ub_local.pipeline.shard_embedded import maybe_shard_embedded_bundle
from ub_local.pipeline.types import BundleType


def build_import_manifest(
    *,
    job_id: str,
    bundle_type: BundleType,
    org_id: str,
    bundle_dir: Path,
    chunk_count: int | None = None,
    filename: str | None = None,
    document_id: str | None = None,
    persona_id: str | None = None,
    include_corpus: bool = True,
    auto_shard: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    embedding_shards = None
    if auto_shard:
        embedding_shards = maybe_shard_embedded_bundle(bundle_dir)

    files: dict[str, Any] = {}
    if include_corpus:
        corpus_path = bundle_dir / CORPUS_FILENAME
        if corpus_path.is_file():
            files[CORPUS_FILENAME] = build_staging_file_entry(corpus_path)

    if embedding_shards:
        if (
            len(embedding_shards) == 1
            and embedding_shards[0]["name"] == CHUNKS_EMBEDDED_FILENAME
        ):
            shard = embedding_shards[0]
            files[CHUNKS_EMBEDDED_FILENAME] = {
                "sha256": shard["sha256"],
                "bytes": shard["bytes"],
            }
        return {
            "job_id": job_id,
            "type": bundle_type,
            "org_id": org_id,
            "files": files,
            "embedding_shards": embedding_shards,
            "embedding_model": settings.embedding_model,
            "dimensions": settings.vector_store_dimension,
            "chunk_count": chunk_count,
            "filename": filename,
            "document_id": document_id,
            "persona_id": persona_id,
        }

    embedded_path = bundle_dir / CHUNKS_EMBEDDED_FILENAME
    files[CHUNKS_EMBEDDED_FILENAME] = build_staging_file_entry(embedded_path)
    return {
        "job_id": job_id,
        "type": bundle_type,
        "org_id": org_id,
        "files": files,
        "embedding_model": settings.embedding_model,
        "dimensions": settings.vector_store_dimension,
        "chunk_count": chunk_count,
        "filename": filename,
        "document_id": document_id,
        "persona_id": persona_id,
    }


def write_import_manifest(bundle_dir: Path, manifest: dict[str, Any]) -> Path:
    path = bundle_dir / IMPORT_MANIFEST_FILENAME
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
