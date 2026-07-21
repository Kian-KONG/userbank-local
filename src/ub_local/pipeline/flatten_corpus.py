from __future__ import annotations

from typing import Any

from ub_local.pipeline.types import FlatChunk


def _paragraph_text(paragraph: Any) -> str:
    if isinstance(paragraph, str):
        return paragraph.strip()
    if isinstance(paragraph, dict):
        return str(paragraph.get("content") or "").strip()
    return ""


def flatten_corpus(corpus: dict[str, Any], document_id: str) -> list[FlatChunk]:
    points: list[FlatChunk] = []
    for node in corpus.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        section_id = str(node.get("id") or "")
        section_title = str(node.get("title") or "")
        paragraphs = node.get("paragraphs") or []
        for p_idx, paragraph in enumerate(paragraphs):
            if isinstance(paragraph, dict) and paragraph.get("type") == "image":
                text = _paragraph_text(paragraph)
                if not text:
                    continue
            else:
                text = _paragraph_text(paragraph)
            if not text:
                continue
            points.append(
                {
                    "id": f"{document_id}:{section_id}:{p_idx}",
                    "text": text,
                    "metadata": {
                        "section_id": section_id,
                        "section_title": section_title,
                        "paragraph_index": p_idx,
                        "chunk_type": "corpus_paragraph",
                    },
                }
            )
    return points
