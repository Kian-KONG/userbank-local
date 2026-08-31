from __future__ import annotations

import gzip
import json
from pathlib import Path

import httpx

from .config import get_settings


async def rag_embed(texts: list[str], input_type: str = "document") -> list[list[float]]:
    if not texts:
        return []
    s = get_settings()
    if s.embed_base_url.strip():
        return await _openai_embed(texts)
    return await _rag_sidecar_embed(texts, input_type)


async def _openai_embed(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    url = f"{s.embed_base_url.rstrip('/')}/embeddings"
    headers = {"Content-Type": "application/json"}
    if s.embed_api_key.strip():
        headers["Authorization"] = f"Bearer {s.embed_api_key.strip()}"
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            url,
            headers=headers,
            json={"model": s.embedding_model, "input": texts},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Embed HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    rows = data.get("data") or []
    rows = sorted(rows, key=lambda r: int(r.get("index", 0)))
    embeddings = [row.get("embedding") for row in rows]
    if len(embeddings) != len(texts):
        raise RuntimeError(f"Embed returned {len(embeddings)}/{len(texts)} vectors")
    out: list[list[float]] = []
    for row in embeddings:
        if not isinstance(row, list):
            raise RuntimeError("Embed response missing embedding vector")
        if len(row) != s.vector_store_dimension:
            raise RuntimeError(
                f"Embed dim {len(row)} != {s.vector_store_dimension}"
            )
        out.append(row)
    return out


async def _rag_sidecar_embed(
    texts: list[str], input_type: str = "document"
) -> list[list[float]]:
    s = get_settings()
    url = f"{s.rag_service_url.rstrip('/')}/api/v1/embeddings"
    headers: dict[str, str] = {}
    if s.rag_internal_secret.strip():
        headers["X-RAG-Secret"] = s.rag_internal_secret.strip()
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            url,
            headers=headers,
            json={
                "texts": texts,
                "model": s.embedding_model,
                "input_type": input_type,
            },
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"RAG embed HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    embeddings = data.get("embeddings") or []
    if len(embeddings) != len(texts):
        raise RuntimeError(f"RAG embed returned {len(embeddings)}/{len(texts)} vectors")
    out: list[list[float]] = []
    for row in embeddings:
        if len(row) != s.vector_store_dimension:
            raise RuntimeError(
                f"RAG embed dim {len(row)} != {s.vector_store_dimension}"
            )
        out.append(row)
    return out


async def rag_ready() -> dict:
    s = get_settings()
    if s.embed_base_url.strip():
        url = f"{s.embed_base_url.rstrip('/')}/models"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
            return {
                "ok": resp.is_success,
                "status": resp.status_code,
                "body": resp.text[:500],
                "mode": "openai-compatible",
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "mode": "openai-compatible"}

    url = f"{s.rag_service_url.rstrip('/')}/health/ready"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        return {
            "ok": resp.is_success,
            "status": resp.status_code,
            "body": resp.text[:500],
            "mode": "userbank-rag",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "mode": "userbank-rag"}


async def rag_describe_pages(pages: list[dict]) -> list[str]:
    """One image per request to userbank-rag vision (qwen3.7-plus)."""
    if not pages:
        return []
    s = get_settings()
    url = f"{s.rag_service_url.rstrip('/')}/api/v1/vision/describe-pages"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if s.rag_internal_secret.strip():
        headers["X-RAG-Secret"] = s.rag_internal_secret.strip()
    descriptions: list[str] = []
    timeout_s = 300.0
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for page in pages:
            payload = {
                "page_number": page.get("page_number"),
                "image_base64": page.get("image_base64"),
            }
            mime = str(page.get("image_mime") or "").strip()
            if mime:
                payload["image_mime"] = mime
            resp = await client.post(
                url,
                headers=headers,
                json={"pages": [payload]},
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Vision HTTP {resp.status_code} page {page.get('page_number')}: {resp.text}"
                )
            rows = resp.json().get("descriptions") or []
            if len(rows) != 1:
                raise RuntimeError(
                    f"Vision returned {len(rows)} descriptions for page {page.get('page_number')}"
                )
            descriptions.append(str(rows[0]))
    return descriptions


async def rag_ingest_table(
    group_id: str,
    document_id: str,
    bundle_dir: Path,
    filename: str | None = None,
) -> dict:
    table_path = Path(bundle_dir) / "crosstab_long.jsonl.gz"
    if not table_path.is_file():
        raise RuntimeError("crosstab_long.jsonl.gz missing")
    rows: list[dict] = []
    with gzip.open(table_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    catalog: list[dict] = []
    catalog_path = Path(bundle_dir) / "question_catalog.json"
    if catalog_path.is_file():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    s = get_settings()
    url = f"{s.rag_service_url.rstrip('/')}/api/v1/tables/ingest"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if s.rag_internal_secret.strip():
        headers["X-RAG-Secret"] = s.rag_internal_secret.strip()
    payload = {
        "group_id": group_id,
        "document_id": document_id,
        "filename": filename,
        "rows": rows,
        "catalog": catalog,
    }
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"RAG table ingest HTTP {resp.status_code}: {resp.text}")
    return resp.json()
