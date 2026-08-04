from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Literal

from ub_local.config import ROOT, get_settings
from ub_local.pipeline.embedded_jsonl import iter_embedded_jsonl_gz
from ub_local.pipeline.import_client import (
    post_import_vectors,
    resolve_knowledge_import_path,
    resolve_survey_import_path,
)
from ub_local.pipeline.manifest import build_import_manifest, write_import_manifest
from ub_local.pipeline.paths import (
    CHUNKS_EMBEDDED_FILENAME,
    CORPUS_FILENAME,
    IMPORT_MANIFEST_FILENAME,
    require_path,
)
from ub_local.pipeline.types import DEFAULT_UPLOAD_BATCH_SIZE, UploadMode

UploadResultMode = Literal["http", "rsync"]


def _resolve_mode(mode: UploadMode | None, bytes_: int) -> UploadResultMode:
    settings = get_settings()
    if mode == "http":
        return "http"
    if mode == "rsync":
        return "rsync"
    return "rsync" if bytes_ >= settings.upload_rsync_min_bytes else "http"


def _load_or_build_manifest(
    bundle_dir: Path, org_id: str, bundle_type: str | None
) -> dict[str, Any]:
    manifest_path = bundle_dir / IMPORT_MANIFEST_FILENAME
    if manifest_path.is_file():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    resolved = bundle_type or (
        "survey" if os.environ.get("BUNDLE_TYPE") == "survey" else "knowledge"
    )
    if resolved not in ("knowledge", "survey"):
        resolved = "knowledge"
    manifest = build_import_manifest(
        job_id=bundle_dir.name or "bundle",
        bundle_type=resolved,  # type: ignore[arg-type]
        org_id=org_id,
        bundle_dir=bundle_dir,
        include_corpus=resolved == "knowledge",
    )
    write_import_manifest(bundle_dir, manifest)
    return manifest


def _upload_knowledge_http(
    *,
    bundle_dir: Path,
    api_url: str,
    org_id: str,
    secret: str,
    manifest: dict[str, Any],
    resume_from_batch: int,
    batch_size: int,
    log: Any,
) -> None:
    embedded_path = bundle_dir / CHUNKS_EMBEDDED_FILENAME
    corpus_path = bundle_dir / CORPUS_FILENAME
    import_path = resolve_knowledge_import_path(api_url)
    chunks = list(iter_embedded_jsonl_gz(embedded_path))
    if not chunks:
        raise RuntimeError("no uploadable knowledge chunks")

    corpus = None
    if corpus_path.is_file():
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))

    total_batches = max(1, (len(chunks) + batch_size - 1) // batch_size)
    filename = manifest.get("filename") or "imported-document"
    document_id = manifest.get("document_id")

    for batch_index in range(total_batches):
        if batch_index < resume_from_batch:
            continue
        start = batch_index * batch_size
        batch = chunks[start : start + batch_size]
        payload = {
            "manifest": {
                "embedding_model": manifest["embedding_model"],
                "dimensions": manifest["dimensions"],
                "filename": filename,
                "batch_index": batch_index,
                "total_batches": total_batches,
                "reset_document": batch_index == 0,
                **({"document_id": document_id} if document_id else {}),
                **({"corpus": corpus} if batch_index == 0 and corpus else {}),
            },
            "chunks": [
                {
                    "id": c["id"],
                    "text": c["text"],
                    "embedding": c["embedding"],
                    "metadata": c.get("metadata") or {},
                }
                for c in batch
            ],
        }
        result = post_import_vectors(api_url, org_id, secret, payload, import_path)
        if batch_index == 0 and isinstance(result.get("documentId"), str):
            document_id = result["documentId"]
        log(
            f"batch {batch_index + 1}/{total_batches}: "
            f"imported={result.get('imported')} totalPages={result.get('totalPages')}"
        )


def _upload_survey_http(
    *,
    bundle_dir: Path,
    api_url: str,
    org_id: str,
    secret: str,
    manifest: dict[str, Any],
    resume_from_batch: int,
    batch_size: int,
    log: Any,
) -> None:
    embedded_path = bundle_dir / CHUNKS_EMBEDDED_FILENAME
    import_path = resolve_survey_import_path(api_url)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for chunk in iter_embedded_jsonl_gz(embedded_path):
        persona_id = manifest.get("persona_id")
        if not persona_id:
            meta = chunk.get("metadata") or {}
            persona_id = meta.get("persona_id") if isinstance(meta.get("persona_id"), str) else None
        if not persona_id:
            continue
        grouped.setdefault(persona_id, []).append(
            {
                "id": chunk["id"],
                "text": chunk["text"],
                "embedding": chunk["embedding"],
                "metadata": chunk.get("metadata") or {},
            }
        )
    if not grouped:
        raise RuntimeError("no uploadable survey chunks")

    for persona_id, chunks in grouped.items():
        total_batches = max(1, (len(chunks) + batch_size - 1) // batch_size)
        log(f"\n{persona_id}: {len(chunks)} chunks, {total_batches} batches")
        for batch_index in range(total_batches):
            if batch_index < resume_from_batch:
                continue
            start = batch_index * batch_size
            batch = chunks[start : start + batch_size]
            payload = {
                "manifest": {
                    "embedding_model": manifest["embedding_model"],
                    "dimensions": manifest["dimensions"],
                    "persona_id": persona_id,
                    "batch_index": batch_index,
                    "total_batches": total_batches,
                    "reset_document": batch_index == 0,
                },
                "chunks": batch,
            }
            result = post_import_vectors(api_url, org_id, secret, payload, import_path)
            log(
                f"  batch {batch_index + 1}/{total_batches}: "
                f"imported={result.get('imported')} totalPages={result.get('totalPages')}"
            )


def _upload_rsync(bundle_dir: Path, manifest: dict[str, Any], ssh_target: str, org_id: str) -> None:
    settings = get_settings()
    script = ROOT / "scripts" / "rsync-upload-bundle.sh"
    require_path(script, "rsync upload script")
    env = {
        **os.environ,
        "SSH_TARGET": ssh_target,
        "IMPORT_STAGING_DIR": settings.import_staging_dir,
        "SURVEY_ORG_ID": org_id,
    }
    proc = subprocess.run(
        [str(script), str(bundle_dir), str(manifest["job_id"])],
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"rsync-upload-bundle.sh exited with code {proc.returncode}")


def upload_bundle(
    *,
    bundle_dir: Path | str,
    api_url: str | None = None,
    org_id: str | None = None,
    secret: str | None = None,
    mode: UploadMode = "auto",
    bundle_type: str | None = None,
    resume_from_batch: int = 0,
    ssh_target: str | None = None,
    batch_size: int | None = None,
    log: Any = print,
) -> dict[str, UploadResultMode]:
    settings = get_settings()
    directory = require_path(bundle_dir, "bundle dir")
    require_path(directory / CHUNKS_EMBEDDED_FILENAME, "embedded chunks file")
    resolved_secret = (secret if secret is not None else settings.survey_import_secret).strip()
    if not resolved_secret:
        raise RuntimeError("SURVEY_IMPORT_SECRET is required")
    resolved_api = (api_url or settings.userbank_api_url).rstrip("/")
    resolved_org = org_id or settings.survey_org_id
    resolved_batch = batch_size or settings.upload_batch_size or DEFAULT_UPLOAD_BATCH_SIZE

    manifest = _load_or_build_manifest(directory, resolved_org, bundle_type)
    bytes_ = (directory / CHUNKS_EMBEDDED_FILENAME).stat().st_size
    resolved_mode = _resolve_mode(mode, bytes_)
    log(f"upload mode={resolved_mode} bundle_bytes={bytes_}")

    if resolved_mode == "rsync":
        target = (ssh_target or settings.ssh_target).strip()
        if not target:
            raise RuntimeError("rsync mode requires SSH_TARGET or --ssh-target")
        _upload_rsync(directory, manifest, target, resolved_org)
        return {"mode": resolved_mode}

    if manifest.get("type") == "survey":
        _upload_survey_http(
            bundle_dir=directory,
            api_url=resolved_api,
            org_id=resolved_org,
            secret=resolved_secret,
            manifest=manifest,
            resume_from_batch=resume_from_batch,
            batch_size=resolved_batch,
            log=log,
        )
    else:
        _upload_knowledge_http(
            bundle_dir=directory,
            api_url=resolved_api,
            org_id=resolved_org,
            secret=resolved_secret,
            manifest=manifest,
            resume_from_batch=resume_from_batch,
            batch_size=resolved_batch,
            log=log,
        )
    return {"mode": resolved_mode}
