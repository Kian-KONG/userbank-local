from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import get_settings
from .jobs import JobStore, health_payload


def create_app(store: JobStore | None = None) -> FastAPI:
    job_store = store or JobStore()
    app = FastAPI(title="userbank-local", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.jobs = job_store

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return await health_payload()

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        job = await job_store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job.to_dict()

    @app.post("/jobs/parse")
    async def jobs_parse(
        file: UploadFile | None = File(None),
        path: str | None = Form(None),
        skip_mineru: str = Form("false"),
    ) -> dict[str, Any]:
        input_path = await _resolve_input(file, path)
        skip = skip_mineru.lower() in {"1", "true", "yes"}
        job = job_store.start_pipeline(
            input_path,
            "knowledge",
            False,
            skip,
            None,
            None,
            None,
        )
        return job.to_dict()

    @app.post("/jobs/export")
    async def jobs_export(body: ExportBody) -> dict[str, Any]:
        job = job_store.start_pipeline(
            Path(body.corpus_path),
            "knowledge",
            False,
            True,
            body.org_id,
            body.document_id,
            body.filename,
        )
        return job.to_dict()

    @app.post("/jobs/upload")
    async def jobs_upload(body: UploadBody) -> dict[str, Any]:
        job = job_store.start_upload(
            Path(body.bundle_dir),
            body.org_id,
        )
        return job.to_dict()

    @app.post("/jobs/pipeline")
    async def jobs_pipeline(
        file: UploadFile | None = File(None),
        path: str | None = Form(None),
        track: str = Form("knowledge"),
        upload: str = Form("true"),
        skip_mineru: str = Form("false"),
        org_id: str | None = Form(None),
        document_id: str | None = Form(None),
        filename: str | None = Form(None),
    ) -> dict[str, Any]:
        input_path = await _resolve_input(file, path, filename)
        do_upload = upload.lower() not in {"0", "false", "no"}
        skip = skip_mineru.lower() in {"1", "true", "yes"}
        resolved_name = filename or (file.filename if file else None)
        job = job_store.start_pipeline(
            input_path,
            track,
            do_upload,
            skip,
            org_id,
            document_id,
            resolved_name,
        )
        return job.to_dict()

    return app


class ExportBody(BaseModel):
    corpus_path: str
    document_id: str | None = None
    filename: str | None = None
    org_id: str | None = None


class UploadBody(BaseModel):
    bundle_dir: str
    org_id: str | None = None


async def _resolve_input(
    file: UploadFile | None,
    path: str | None,
    filename_hint: str | None = None,
) -> Path:
    s = get_settings()
    if file is not None and file.filename:
        dest = s.work_dir() / "uploads" / file.filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(await file.read())
        return dest
    if path:
        return Path(path)
    raise HTTPException(status_code=400, detail="file or path required")
