from __future__ import annotations

from typing import Any

DECK_OVERVIEW_MARKER = "[deck_overview]"
PAGE_ROLES = ("title", "agenda", "evidence", "conclusion", "appendix")


def flatten_for_export(corpus: dict[str, Any], document_id: str) -> list[dict[str, Any]]:
    if corpus.get("source_type") == "image" or (
        isinstance(corpus.get("pages"), list) and not corpus.get("nodes")
    ):
        return flatten_deck(corpus, document_id)
    return flatten_corpus(corpus, document_id)


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


def flatten_deck(corpus: dict[str, Any], document_id: str) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    overview_text = format_overview_text(corpus.get("overview") or {})
    if overview_text:
        points.append(
            {
                "id": f"{document_id}:overview",
                "text": overview_text,
                "metadata": {
                    "chunk_type": "deck_overview",
                    "page_number": 0,
                    "section": "overview",
                    "role": "title",
                },
            }
        )
    pages = corpus.get("pages") or []
    if not isinstance(pages, list):
        return points
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_number = int(page.get("page_number") or 0)
        description = str(page.get("description") or "").strip()
        if page_number < 1 or not description:
            continue
        section = str(page.get("section") or "").strip()
        role = str(page.get("role") or "evidence").strip() or "evidence"
        continues = page.get("continues")
        prefix = format_page_prefix(page_number, section, role, continues)
        refers_to = page.get("refers_to") if isinstance(page.get("refers_to"), list) else []
        points.append(
            {
                "id": f"{document_id}:{page_number}",
                "text": f"{prefix}\n{description}",
                "metadata": {
                    "chunk_type": "image_page",
                    "page_number": page_number,
                    "section": section,
                    "role": role,
                    "continues": continues,
                    "refers_to": refers_to,
                    "title": str(page.get("title") or ""),
                },
            }
        )
    return points


def format_page_prefix(
    page_number: int,
    section: str,
    role: str,
    continues: Any,
) -> str:
    parts = [f"Slide {page_number}"]
    if section:
        parts.append(section)
    parts.append(role)
    if isinstance(continues, int) and continues > 0:
        parts.append(f"continues {continues}")
    return "[" + " | ".join(parts) + "]"


def format_overview_text(overview: dict[str, Any]) -> str:
    argument = str(overview.get("argument") or "").strip()
    outline = overview.get("outline") or []
    lines = [DECK_OVERVIEW_MARKER]
    if argument:
        lines.append("Argument:")
        lines.append(argument)
    if isinstance(outline, list) and outline:
        lines.append("Outline:")
        for entry in outline:
            if not isinstance(entry, dict):
                continue
            section = str(entry.get("section") or "").strip()
            claim = str(entry.get("claim") or "").strip()
            pages = entry.get("pages") or []
            page_label = ""
            if isinstance(pages, list) and pages:
                page_label = f" (pages {', '.join(str(p) for p in pages)})"
            if section and claim:
                lines.append(f"- {section}{page_label}: {claim}")
            elif section or claim:
                lines.append(f"- {section or claim}{page_label}")
    body = "\n".join(lines).strip()
    return body if body != DECK_OVERVIEW_MARKER else ""


def paragraph_text(paragraph: Any) -> str:
    if isinstance(paragraph, str):
        return paragraph.strip()
    if isinstance(paragraph, dict):
        return str(paragraph.get("content") or "").strip()
    return ""
