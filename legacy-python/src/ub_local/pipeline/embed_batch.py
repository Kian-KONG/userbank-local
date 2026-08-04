from __future__ import annotations

from ub_local.config import get_settings
from ub_local.pipeline.types import EmbeddedChunk, FlatChunk
from ub_local.rag_client import rag_embed


def embed_flat_chunks(chunks: list[FlatChunk]) -> list[EmbeddedChunk]:
    if not chunks:
        return []
    settings = get_settings()
    vectors = rag_embed([c["text"] for c in chunks], input_type="document")
    out: list[EmbeddedChunk] = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        if len(vector) != settings.vector_store_dimension:
            raise RuntimeError(
                f"dim {len(vector)} != {settings.vector_store_dimension} (chunk={chunk["id"]})"
            )
        out.append({**chunk, "embedding": vector})
    return out
