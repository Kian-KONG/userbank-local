from __future__ import annotations

import asyncio
import gzip
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .config import get_settings
from .flatten import flatten_for_export
from .rag import rag_embed

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
    manifest = {
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
    }
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


def read_jsonl_gz(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def resolve_knowledge_import_path(api_url: str) -> str:
    if ":3000" in api_url or "127.0.0.1" in api_url or "localhost" in api_url:
        return "/knowledge/import-vectors"
    return "/api/knowledge/import-vectors"


async def upload_bundle(
    bundle_dir: Path,
    mode: str = "auto",
    org_id: str | None = None,
    api_url: str | None = None,
) -> dict[str, Any]:
    s = get_settings()
    org = org_id or s.survey_org_id
    api = (api_url or s.userbank_api_url).rstrip("/")
    secret = s.survey_import_secret.strip()
    if not secret:
        raise RuntimeError("SURVEY_IMPORT_SECRET is required for upload")

    manifest = json.loads((bundle_dir / "import.manifest.json").read_text(encoding="utf-8"))
    chunks = read_jsonl_gz(bundle_dir / "chunks.embedded.jsonl.gz")
    import_path = resolve_knowledge_import_path(api)
    payload = {
        "manifest": manifest,
        "chunks": [
            {
                "id": c.get("id"),
                "text": c.get("text"),
                "embedding": c.get("embedding"),
                "metadata": c.get("metadata") or {},
            }
            for c in chunks
        ],
    }

    use_http = mode == "http" or (
        mode == "auto" and dir_size(bundle_dir) < s.upload_rsync_min_bytes
    )
    if not use_http:
        raise RuntimeError(
            "rsync mode not implemented in Python CLI yet; use --mode http or smaller bundles"
        )

    from urllib.parse import quote

    url = f"{api}{import_path}?groupId={quote(org)}"
    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=300.0) as client:
        for attempt in range(s.upload_http_retries + 1):
            try:
                resp = await client.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "x-survey-import-secret": secret,
                    },
                    json=payload,
                )
                if resp.is_success:
                    try:
                        body = resp.json()
                    except Exception:  # noqa: BLE001
                        body = {"ok": True}
                    return {"mode": "http", "result": body}
                last_err = RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
            except Exception as exc:  # noqa: BLE001
                last_err = exc
            if attempt < s.upload_http_retries:
                await asyncio.sleep(1 << attempt)
    raise last_err or RuntimeError("upload failed")
