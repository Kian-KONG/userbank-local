from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import get_settings
from .flatten import PAGE_ROLES

SYNTH_PROMPT = """You are structuring a slide deck for retrieval.
Given ordered page summaries (not full OCR), produce JSON only with:
{
  "argument": "3-8 sentences: the deck's thesis and line of reasoning",
  "outline": [{"section": "name", "pages": [1, 2], "claim": "what this section argues"}],
  "pages": [{"page": 1, "section": "name", "role": "title|agenda|evidence|conclusion|appendix", "continues": null, "refers_to": []}]
}
Rules:
- role must be one of: title, agenda, evidence, conclusion, appendix
- continues: previous page number if this slide continues it, else null
- refers_to: page numbers this slide depends on (legend, definition, prior chart); may be empty
- Do not invent facts that are not in the summaries.
- Keep section names stable across adjacent pages of the same topic.
"""


def page_summary(page_number: int, title: str, description: str, limit: int) -> str:
    first_line = (title or "").strip() or first_title_line(description)
    body = re.sub(r"\s+", " ", (description or "").strip())
    if limit > 0:
        body = body[:limit]
    return f"Page {page_number}: {first_line}\n{body}".strip()


def first_title_line(description: str) -> str:
    for line in (description or "").splitlines():
        text = line.strip().lstrip("#").strip()
        if text:
            return text[:180]
    return ""


def parse_synth_json(raw: str, page_numbers: list[int]) -> dict[str, Any]:
    parsed = _load_json_object(raw)
    roles = set(PAGE_ROLES)
    pages_out: list[dict[str, Any]] = []
    raw_pages = parsed.get("pages") if isinstance(parsed.get("pages"), list) else []
    by_page: dict[int, dict[str, Any]] = {}
    for entry in raw_pages:
        if not isinstance(entry, dict):
            continue
        try:
            page = int(entry.get("page") or entry.get("page_number") or 0)
        except (TypeError, ValueError):
            continue
        if page < 1:
            continue
        role = str(entry.get("role") or "evidence").strip().lower()
        if role not in roles:
            role = "evidence"
        continues = entry.get("continues")
        if continues is not None:
            try:
                continues = int(continues)
            except (TypeError, ValueError):
                continues = None
        refers = entry.get("refers_to") if isinstance(entry.get("refers_to"), list) else []
        refers_to = []
        for item in refers:
            try:
                num = int(item)
            except (TypeError, ValueError):
                continue
            if num > 0:
                refers_to.append(num)
        by_page[page] = {
            "page": page,
            "section": str(entry.get("section") or "").strip(),
            "role": role,
            "continues": continues if isinstance(continues, int) and continues > 0 else None,
            "refers_to": refers_to,
        }
    for page in page_numbers:
        pages_out.append(
            by_page.get(
                page,
                {
                    "page": page,
                    "section": "",
                    "role": "evidence",
                    "continues": None,
                    "refers_to": [],
                },
            )
        )
    outline = []
    for entry in parsed.get("outline") or []:
        if not isinstance(entry, dict):
            continue
        pages = []
        for item in entry.get("pages") or []:
            try:
                pages.append(int(item))
            except (TypeError, ValueError):
                continue
        outline.append(
            {
                "section": str(entry.get("section") or "").strip(),
                "pages": pages,
                "claim": str(entry.get("claim") or "").strip(),
            }
        )
    return {
        "argument": str(parsed.get("argument") or "").strip(),
        "outline": outline,
        "pages": pages_out,
    }


def _load_json_object(raw: str) -> dict[str, Any]:
    trimmed = (raw or "").strip()
    if not trimmed:
        raise ValueError("Deck synthesizer returned empty response")
    try:
        parsed = json.loads(trimmed)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", trimmed)
        if not match:
            start = trimmed.find("{")
            end = trimmed.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("Deck synthesizer response was not JSON") from None
            parsed = json.loads(trimmed[start : end + 1])
        else:
            parsed = json.loads(match.group(1).strip())
    if not isinstance(parsed, dict):
        raise ValueError("Deck synthesizer JSON must be an object")
    return parsed


async def synthesize_deck(pages: list[dict[str, Any]]) -> dict[str, Any]:
    if not pages:
        raise ValueError("No pages to synthesize")
    s = get_settings()
    if not s.llm_api_key.strip():
        raise RuntimeError("LLM_API_KEY is required for deck synthesis")
    limit = max(80, int(s.synth_page_summary_chars))
    summaries = [
        page_summary(
            int(page["page_number"]),
            str(page.get("title") or ""),
            str(page.get("description") or ""),
            limit,
        )
        for page in pages
    ]
    content = SYNTH_PROMPT + "\n\n" + "\n\n".join(summaries)
    timeout_s = 180.0
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            s.llm_api_url,
            json={
                "model": s.llm_synth_model,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": 8192,
            },
            headers={
                "Authorization": f"Bearer {s.llm_api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout_s,
        )
    if resp.is_error:
        raise RuntimeError(
            f"Deck synth HTTP {resp.status_code}: {resp.text.strip() or resp.reason_phrase}"
        )
    raw = resp.json()["choices"][0]["message"]["content"]
    page_numbers = [int(page["page_number"]) for page in pages]
    return parse_synth_json(raw, page_numbers)
