from __future__ import annotations

import asyncio
import gzip
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import get_settings
from .flatten import flatten_for_export
from .rag import rag_embed
from .rsync_upload import attach_checksums, rsync_upload_bundle

BATCH = 16

ProgressCb = Callable[[int, int], Any]


def ensure_output_subdir(name: str) -> Path:
    directory = get_settings().work_dir() / name
    directory.mkdir(parents=True, exist_ok=True)
    return directory


async def export_knowledge_bundle(
    corpus_path: Path,
    output_dir: Path,
    document_id: str,
    filename: str | None = None,
    org_id: str | None = None,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    s = get_settings()
    output_dir.mkdir(parents=True, exist_ok=True)
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    flat = flatten_for_export(corpus, document_id)
    if not flat:
        raise RuntimeError("corpus produced no embeddable paragraphs")

    (output_dir / "doc_corpus.json").write_text(
        json.dumps(corpus, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    embedded_items: list[dict[str, Any]] = []
    total = len(flat)
    for start in range(0, total, BATCH):
        chunk = flat[start : start + BATCH]
        texts = [c["text"] for c in chunk]
        vectors = await rag_embed(texts, "document")
        for item, vector in zip(chunk, vectors):
            embedded_items.append(
                {
                    "id": item["id"],
                    "text": item["text"],
                    "embedding": vector,
                    "metadata": item["metadata"],
                }
            )
            if on_progress is not None:
                maybe = on_progress(len(embedded_items), total)
                if asyncio.iscoroutine(maybe):
                    await maybe

    write_jsonl_gz(output_dir / "chunks.embedded.jsonl.gz", embedded_items)

    resolved_org = org_id or s.survey_org_id
    fname = filename or corpus_path.name or "document.json"
    manifest = attach_checksums(
        {
            "embedding_model": s.embedding_model,
            "dimensions": s.vector_store_dimension,
            "filename": fname,
            "document_id": document_id,
            "batch_index": 0,
            "total_batches": 1,
            "reset_document": True,
            "org_id": resolved_org,
            "job_id": str(uuid.uuid4()),
            "chunk_count": len(embedded_items),
            "source_type": corpus.get("source_type") or "text",
        },
        output_dir,
    )
    (output_dir / "import.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "output_dir": str(output_dir),
        "document_id": document_id,
        "chunk_count": len(embedded_items),
        "org_id": resolved_org,
    }


def write_jsonl_gz(path: Path, items: list[dict[str, Any]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")


async def upload_bundle(
    bundle_dir: Path,
    org_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(rsync_upload_bundle, bundle_dir, job_id, org_id)
