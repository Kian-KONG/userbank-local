from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ub_local.api.jobs import (
    STORE,
    job_to_dict,
    start_export_job,
    start_parse_job,
    start_pipeline_job,
    start_upload_job,
)
from ub_local.config import get_settings
from ub_local.orchestrate.parse import check_deepread, check_mineru
from ub_local.rag_client import rag_ready

app = FastAPI(title="userbank-local", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExportBody(BaseModel):
    corpus_path: str
    document_id: str = "local-doc"
    filename: str | None = None
    org_id: str | None = None


class UploadBody(BaseModel):
    bundle_dir: str
    mode: str = "auto"
    org_id: str | None = None


@app.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "ok": True,
        "host": settings.ub_local_host,
        "port": settings.ub_local_port,
        "rag": rag_ready(),
        "mineru": check_mineru(),
        "deepread": check_deepread(),
        "ssh_configured": bool(settings.ssh_target.strip()),
        "org_id": settings.survey_org_id,
        "api_url": settings.userbank_api_url,
        "work_dir": str(settings.work_dir()),
    }


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job_to_dict(job)


@app.post("/jobs/parse")
async def jobs_parse(
    file: UploadFile | None = File(None),
    path: str | None = Form(None),
    skip_mineru: bool = Form(False),
) -> dict[str, Any]:
    settings = get_settings()
    input_path = await _resolve_input(file, path, settings.work_dir() / "uploads")
    job = start_parse_job(input_path, skip_mineru=skip_mineru)
    return job_to_dict(job)


@app.post("/jobs/export")
def jobs_export(body: ExportBody) -> dict[str, Any]:
    job = start_export_job(
        body.corpus_path,
        document_id=body.document_id,
        filename=body.filename,
        org_id=body.org_id,
    )
    return job_to_dict(job)


@app.post("/jobs/upload")
def jobs_upload(body: UploadBody) -> dict[str, Any]:
    job = start_upload_job(body.bundle_dir, mode=body.mode, org_id=body.org_id)
    return job_to_dict(job)


@app.post("/jobs/pipeline")
async def jobs_pipeline(
    file: UploadFile | None = File(None),
    path: str | None = Form(None),
    document_id: str | None = Form(None),
    filename: str | None = Form(None),
    org_id: str | None = Form(None),
    mode: str = Form("auto"),
    skip_mineru: bool = Form(False),
    upload: bool = Form(True),
) -> dict[str, Any]:
    settings = get_settings()
    input_path = await _resolve_input(file, path, settings.work_dir() / "uploads")
    job = start_pipeline_job(
        input_path,
        document_id=document_id,
        filename=filename or (file.filename if file else None),
        org_id=org_id,
        mode=mode,
        skip_mineru=skip_mineru,
        upload=upload,
    )
    return job_to_dict(job)


async def _resolve_input(
    file: UploadFile | None, path: str | None, upload_dir: Path
) -> str:
    if path and path.strip():
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise HTTPException(400, f"path not found: {p}")
        return str(p)
    if file is None:
        raise HTTPException(400, "provide multipart file or form field path=")
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / (file.filename or f"upload-{Path(file.filename or 'bin').name}")
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return str(dest.resolve())
