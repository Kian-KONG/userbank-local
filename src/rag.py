from __future__ import annotations

import httpx

from .config import get_settings


async def rag_embed(texts: list[str], input_type: str = "document") -> list[list[float]]:
    if not texts:
        return []
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
    url = f"{s.rag_service_url.rstrip('/')}/health/ready"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        return {
            "ok": resp.is_success,
            "status": resp.status_code,
            "body": resp.text[:500],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
