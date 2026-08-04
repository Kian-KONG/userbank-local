from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import quote

import httpx

from ub_local.config import get_settings

TRANSIENT = {429, 502, 503, 504}


def resolve_knowledge_import_path(api_url: str) -> str:
    override = os.environ.get("KNOWLEDGE_IMPORT_PATH", "").strip()
    if override:
        return override
    if ":3000" in api_url or "127.0.0.1" in api_url or "localhost" in api_url:
        return "/knowledge/import-vectors"
    return "/api/knowledge/import-vectors"


def resolve_survey_import_path(api_url: str) -> str:
    override = os.environ.get("SURVEY_IMPORT_PATH", "").strip()
    if override:
        return override
    if ":3000" in api_url or "127.0.0.1" in api_url or "localhost" in api_url:
        return "/survey/import-vectors"
    return "/api/survey/import-vectors"


def post_import_vectors(
    api_url: str,
    org_id: str,
    secret: str,
    payload: Any,
    import_path: str,
    *,
    timeout_ms: int = 300_000,
) -> dict[str, Any]:
    settings = get_settings()
    url = f"{api_url.rstrip('/')}{import_path}?groupId={quote(org_id)}"
    retries = settings.upload_http_retries
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout_ms / 1000) as client:
                resp = client.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "x-survey-import-secret": secret,
                    },
                    json=payload,
                )
                if resp.status_code in TRANSIENT and attempt < retries:
                    time.sleep(2**attempt)
                    continue
                if resp.status_code >= 400:
                    raise RuntimeError(
                        f"HTTP {resp.status_code} {url}: {resp.text[:1000]}"
                    )
                return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(2**attempt)
                continue
            raise
    raise last_err or RuntimeError(f"HTTP request failed {url}")
