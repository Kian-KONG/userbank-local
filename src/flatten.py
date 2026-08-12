from __future__ import annotations

from typing import Any


def flatten_corpus(corpus: dict[str, Any], document_id: str) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    nodes = corpus.get("nodes") or []
    if not isinstance(nodes, list):
        return points
    for node in nodes:
        if not isinstance(node, dict):
            continue
        section_id = str(node.get("id") or "")
        section_title = str(node.get("title") or "")
        paragraphs = node.get("paragraphs") or []
        if not isinstance(paragraphs, list):
            continue
        for p_idx, paragraph in enumerate(paragraphs):
            text = paragraph_text(paragraph)
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


def paragraph_text(paragraph: Any) -> str:
    if isinstance(paragraph, str):
        return paragraph.strip()
    if isinstance(paragraph, dict):
        return str(paragraph.get("content") or "").strip()
    return ""
