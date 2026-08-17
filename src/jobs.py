from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import get_settings
from .orchestrate import check_deepread, check_mineru, parse_document
from .pipeline import ensure_output_subdir, export_knowledge_bundle, upload_bundle
from .rag import rag_ready


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    kind: str
    state: str = "pending"
    phase: str = "queued"
    progress: float = 0.0
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    logs: list[str] = field(default_factory=list)

    @classmethod
    def new(cls, kind: str) -> Job:
        return cls(id=str(uuid.uuid4()), kind=kind)

    def log(self, msg: str) -> None:
        self.logs.append(f"[{_now()}] {msg}")
        if len(self.logs) > 2000:
            self.logs = self.logs[-1500:]

    def set_progress(self, phase: str, progress: float, msg: str | None = None) -> None:
        self.phase = phase
        self.progress = max(0.0, min(100.0, progress))
        if msg:
            self.log(f"[{phase} {self.progress:.0f}%] {msg}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "phase": self.phase,
            "progress": self.progress,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "result": self.result,
            "logs": list(self.logs),
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()
        self._limit = asyncio.Semaphore(2)

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            return job

    def get_sync(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def upsert(self, job: Job) -> None:
        async with self._lock:
            self._jobs[job.id] = job

    def upsert_sync(self, job: Job) -> None:
        self._jobs[job.id] = job

    async def mutate(self, job_id: str, fn: Callable[[Job], None]) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                fn(job)

    def start_pipeline(
        self,
        input_path: Path,
        track: str,
        mode: str,
        upload: bool,
        skip_mineru: bool,
        org_id: str | None,
        document_id: str | None,
        filename: str | None,
    ) -> Job:
        job = Job.new("pipeline")
        self.upsert_sync(job)
        asyncio.create_task(
            self._run_pipeline_task(
                job.id,
                input_path,
                track,
                mode,
                upload,
                skip_mineru,
                org_id,
                document_id,
                filename,
            )
        )
        return job

    def start_upload(
        self,
        bundle_dir: Path,
        mode: str,
        org_id: str | None,
    ) -> Job:
        job = Job.new("upload")
        self.upsert_sync(job)
        asyncio.create_task(self._run_upload_task(job.id, bundle_dir, mode, org_id))
        return job

    async def _run_upload_task(
        self,
        job_id: str,
        bundle_dir: Path,
        mode: str,
        org_id: str | None,
    ) -> None:
        def mark_running(j: Job) -> None:
            j.state = "running"
            j.started_at = _now()

        await self.mutate(job_id, mark_running)
        try:
            result = await upload_bundle(bundle_dir, mode, org_id, None)

            def done(j: Job) -> None:
                j.state = "done"
                j.result = result
                j.phase = "done"
                j.progress = 100.0
                j.finished_at = _now()

            await self.mutate(job_id, done)
        except Exception as exc:  # noqa: BLE001

            def fail(j: Job) -> None:
                j.state = "failed"
                j.error = str(exc)
                j.finished_at = _now()

            await self.mutate(job_id, fail)

    async def _run_pipeline_task(
        self,
        job_id: str,
        input_path: Path,
        track: str,
        mode: str,
        upload: bool,
        skip_mineru: bool,
        org_id: str | None,
        document_id: str | None,
        filename: str | None,
    ) -> None:
        async with self._limit:

            def mark_running(j: Job) -> None:
                j.state = "running"
                j.started_at = _now()
                j.set_progress("parse", 5.0, "starting pipeline")

            await self.mutate(job_id, mark_running)
            try:
                result = await run_pipeline(
                    self,
                    job_id,
                    input_path,
                    track,
                    mode,
                    upload,
                    skip_mineru,
                    org_id,
                    document_id,
                    filename,
                )

                def done(j: Job) -> None:
                    j.state = "done"
                    j.result = result
                    j.set_progress("done", 100.0, "finished")
                    j.finished_at = _now()

                await self.mutate(job_id, done)
            except Exception as exc:  # noqa: BLE001

                def fail(j: Job) -> None:
                    j.state = "failed"
                    j.phase = "failed"
                    j.error = str(exc)
                    j.log(str(exc))
                    j.finished_at = _now()

                await self.mutate(job_id, fail)


async def run_pipeline(
    store: JobStore,
    job_id: str,
    input_path: Path,
    track: str,
    mode: str,
    upload: bool,
    skip_mineru: bool,
    org_id: str | None,
    document_id: str | None,
    filename: str | None,
) -> dict[str, Any]:
    work = ensure_output_subdir(f"jobs/{job_id}")
    await store.mutate(job_id, lambda j: j.set_progress("parse", 10.0, "parsing"))
    if track == "image":
        from .image_ingest import ingest_image_document

        async def on_vision(phase: str, done: int, total: int) -> None:
            pct = 10.0 + 45.0 * (done / max(total, 1))
            await store.mutate(
                job_id,
                lambda j: j.set_progress(
                    "vision", pct, f"{phase} {done}/{total}"
                ),
            )

        corpus = await ingest_image_document(
            input_path, work / "parse", on_vision
        )
        embed_start = 60.0
    else:
        corpus = await asyncio.to_thread(
            parse_document, input_path, work / "parse", skip_mineru
        )
        embed_start = 35.0
    await store.mutate(job_id, lambda j: j.set_progress("embed", embed_start, "export + embed"))
    doc_id = document_id or "local-doc"
    export_dir = work / "bundle"

    async def on_progress(done: int, total: int) -> None:
        pct = embed_start + (90.0 - embed_start) * (done / max(total, 1))
        await store.mutate(
            job_id,
            lambda j: j.set_progress("embed", pct, f"embedded {done}/{total}"),
        )

    export = await export_knowledge_bundle(
        corpus,
        export_dir,
        doc_id,
        filename,
        org_id,
        on_progress,
    )

    if not upload:
        return {"export": export, "uploaded": False}
    await store.mutate(job_id, lambda j: j.set_progress("upload", 90.0, "uploading"))
    uploaded = await upload_bundle(export_dir, mode, org_id, None)
    return {"export": export, "upload": uploaded}


async def health_payload() -> dict[str, Any]:
    s = get_settings()
    return {
        "ok": True,
        "host": s.ub_local_host,
        "port": s.ub_local_port,
        "rag": await rag_ready(),
        "mineru": check_mineru(),
        "deepread": check_deepread(),
        "ssh_configured": bool(s.ssh_target.strip()),
        "org_id": s.survey_org_id,
        "api_url": s.userbank_api_url,
        "work_dir": str(s.work_dir()),
    }
