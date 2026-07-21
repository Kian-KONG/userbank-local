from __future__ import annotations

import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal
from ub_local.config import get_settings
from ub_local.orchestrate.parse import parse_document
from ub_local.pipeline.export_knowledge import export_knowledge_bundle
from ub_local.pipeline.upload import upload_bundle

JobKind = Literal["parse", "export", "upload", "pipeline"]
JobState = Literal["pending", "running", "done", "failed"]


@dataclass
class Job:
    id: str
    kind: JobKind
    state: JobState = "pending"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    logs: list[str] = field(default_factory=list)

    def log(self, msg: str) -> None:
        line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
        self.logs.append(line)
        if len(self.logs) > 2000:
            self.logs = self.logs[-1500:]


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=2)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def create(self, kind: JobKind) -> Job:
        job = Job(id=str(uuid.uuid4()), kind=kind)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def submit(self, job: Job, fn: Callable[[Job], None]) -> Job:
        def runner() -> None:
            job.state = "running"
            job.started_at = datetime.now(timezone.utc).isoformat()
            try:
                fn(job)
                job.state = "done"
            except Exception as exc:  # noqa: BLE001
                job.state = "failed"
                job.error = str(exc)
                job.log(traceback.format_exc()[-3000:])
            finally:
                job.finished_at = datetime.now(timezone.utc).isoformat()

        self._pool.submit(runner)
        return job


STORE = JobStore()


def start_parse_job(input_path: str, *, skip_mineru: bool = False) -> Job:
    settings = get_settings()
    job = STORE.create("parse")

    def run(j: Job) -> None:
        corpus = parse_document(
            input_path,
            settings.work_dir() / j.id,
            skip_mineru=skip_mineru,
            log=j.log,
        )
        j.result = {"corpus_path": str(corpus)}

    return STORE.submit(job, run)


def start_export_job(
    corpus_path: str,
    *,
    document_id: str = "local-doc",
    filename: str | None = None,
    org_id: str | None = None,
) -> Job:
    settings = get_settings()
    job = STORE.create("export")

    def run(j: Job) -> None:
        out = settings.work_dir() / j.id / "bundle"
        result = export_knowledge_bundle(
            corpus_path=corpus_path,
            output_dir=out,
            document_id=document_id,
            org_id=org_id,
            job_id=j.id,
            filename=filename,
            log=j.log,
        )
        j.result = result

    return STORE.submit(job, run)


def start_upload_job(
    bundle_dir: str,
    *,
    mode: str = "auto",
    org_id: str | None = None,
) -> Job:
    job = STORE.create("upload")

    def run(j: Job) -> None:
        result = upload_bundle(
            bundle_dir=bundle_dir,
            mode=mode,  # type: ignore[arg-type]
            org_id=org_id,
            log=j.log,
        )
        j.result = dict(result)

    return STORE.submit(job, run)


def start_pipeline_job(
    input_path: str,
    *,
    document_id: str | None = None,
    filename: str | None = None,
    org_id: str | None = None,
    mode: str = "auto",
    skip_mineru: bool = False,
    upload: bool = True,
) -> Job:
    settings = get_settings()
    job = STORE.create("pipeline")
    doc_id = document_id or Path(input_path).stem
    fname = filename or Path(input_path).name

    def run(j: Job) -> None:
        work = settings.work_dir() / j.id
        corpus = parse_document(
            input_path, work, skip_mineru=skip_mineru, log=j.log
        )
        j.log(f"corpus ready: {corpus}")
        bundle = export_knowledge_bundle(
            corpus_path=corpus,
            output_dir=work / "bundle",
            document_id=doc_id,
            org_id=org_id,
            job_id=j.id,
            filename=fname,
            log=j.log,
        )
        result: dict[str, Any] = {"corpus_path": str(corpus), **bundle}
        if upload:
            up = upload_bundle(
                bundle_dir=bundle["output_dir"],
                mode=mode,  # type: ignore[arg-type]
                org_id=org_id,
                log=j.log,
            )
            result["upload"] = dict(up)
        j.result = result

    return STORE.submit(job, run)


def job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "state": job.state,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error,
        "result": job.result,
        "logs": job.logs[-200:],
    }
