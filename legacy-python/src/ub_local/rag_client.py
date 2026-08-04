from __future__ import annotations

import httpx

from ub_local.config import get_settings


def rag_embed(texts: list[str], *, input_type: str = "document") -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    url = settings.rag_service_url.rstrip("/") + "/api/v1/embeddings"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.rag_internal_secret.strip():
        headers["X-RAG-Secret"] = settings.rag_internal_secret.strip()

    with httpx.Client(timeout=300.0) as client:
        resp = client.post(
            url,
            headers=headers,
            json={
                "texts": texts,
                "model": settings.embedding_model,
                "input_type": input_type,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    embeddings = data.get("embeddings") or []
    if len(embeddings) != len(texts):
        raise RuntimeError(f"RAG embed returned {len(embeddings)}/{len(texts)} vectors")
    for vector in embeddings:
        if len(vector) != settings.vector_store_dimension:
            raise RuntimeError(
                f"RAG embed dim {len(vector)} != {settings.vector_store_dimension}"
            )
    return embeddings


def rag_ready() -> dict:
    settings = get_settings()
    url = settings.rag_service_url.rstrip("/") + "/health/ready"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)
            return {"ok": resp.status_code == 200, "status": resp.status_code, "body": resp.text[:500]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
