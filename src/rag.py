from __future__ import annotations

import httpx

from .config import get_settings


async def rag_embed(texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Embed texts via local OpenAI-compatible API (preferred) or userbank-rag."""
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
    # OpenAI format may not preserve input order guarantees across providers;
    # sort by index when present.
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
            resp = await client.post(
                url,
                headers=headers,
                json={"pages": [page]},
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

