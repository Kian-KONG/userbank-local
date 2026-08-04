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
from ub_local.orchestrate.survey_parse import parse_survey_input
from ub_local.pipeline.embed_seed import embed_seed_bundle
from ub_local.pipeline.export_knowledge import export_knowledge_bundle
from ub_local.pipeline.upload import upload_bundle

JobKind = Literal["parse", "export", "upload", "pipeline"]
JobState = Literal["pending", "running", "done", "failed"]
JobPhase = Literal[
    "queued",
    "parse",
    "embed",
    "upload",
    "done",
    "failed",
]
Track = Literal["knowledge", "survey"]


@dataclass
class Job:
    id: str
    kind: JobKind
    state: JobState = "pending"
    phase: JobPhase = "queued"
    progress: float = 0.0  # 0–100
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

    def set_progress(self, phase: JobPhase, progress: float, msg: str | None = None) -> None:
        self.phase = phase
        self.progress = max(0.0, min(100.0, float(progress)))
        if msg:
            self.log(f"[{phase} {self.progress:.0f}%] {msg}")


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
                job.set_progress("done", 100.0, "finished")
            except Exception as exc:  # noqa: BLE001
                job.state = "failed"
                job.phase = "failed"
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
        j.set_progress("parse", 5.0, f"parsing {input_path}")
        corpus = parse_document(
            input_path,
            settings.work_dir() / j.id,
            skip_mineru=skip_mineru,
            log=j.log,
        )
        j.set_progress("parse", 100.0, f"corpus ready: {corpus}")
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
        j.set_progress("embed", 5.0, "embedding knowledge corpus")
        out = settings.work_dir() / j.id / "bundle"

        def on_embed(done: int, total: int) -> None:
            pct = 5.0 + (90.0 * done / max(total, 1))
            j.set_progress("embed", pct, f"embedded {done}/{total}")

        result = export_knowledge_bundle(
            corpus_path=corpus_path,
            output_dir=out,
            document_id=document_id,
            org_id=org_id,
            job_id=j.id,
            filename=filename,
            log=j.log,
            on_progress=on_embed,
        )
        j.set_progress("embed", 100.0, f"bundle at {result['output_dir']}")
        j.result = result

    return STORE.submit(job, run)


def start_upload_job(
    bundle_dir: str,
    *,
    mode: str = "auto",
    org_id: str | None = None,
    bundle_type: str | None = None,
) -> Job:
    job = STORE.create("upload")

    def run(j: Job) -> None:
        j.set_progress("upload", 5.0, f"uploading {bundle_dir}")
        result = upload_bundle(
            bundle_dir=bundle_dir,
            mode=mode,  # type: ignore[arg-type]
            org_id=org_id,
            bundle_type=bundle_type,
            log=j.log,
        )
        j.set_progress("upload", 100.0, f"mode={result['mode']}")
        j.result = dict(result)

    return STORE.submit(job, run)


def start_pipeline_job(
    input_path: str,
    *,
    track: Track = "knowledge",
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
        result: dict[str, Any] = {"track": track}

        if track == "survey":
            j.set_progress("parse", 5.0, "parsing survey input (xlsx/docx/jsonl)")
            chunks_path = parse_survey_input(input_path, work / "survey", log=j.log)
            j.set_progress("parse", 30.0, f"chunks ready: {chunks_path}")

            def on_embed(done: int, total: int) -> None:
                pct = 30.0 + (50.0 * done / max(total, 1))
                j.set_progress("embed", pct, f"embedded {done}/{total}")

            j.set_progress("embed", 32.0, "embedding survey chunks")
            bundle = embed_seed_bundle(
                chunks_path=chunks_path,
                output_dir=work / "bundle",
                org_id=org_id,
                job_id=j.id,
                log=j.log,
                on_progress=on_embed,
            )
            result.update({"chunks_path": str(chunks_path), **bundle})
            bundle_dir = bundle["output_dir"]
            bundle_type = "survey"
        else:
            j.set_progress("parse", 5.0, "parsing PDF/md via MinerU/DeepRead")
            corpus = parse_document(
                input_path, work, skip_mineru=skip_mineru, log=j.log
            )
            j.set_progress("parse", 30.0, f"corpus ready: {corpus}")

            def on_embed(done: int, total: int) -> None:
                pct = 30.0 + (50.0 * done / max(total, 1))
                j.set_progress("embed", pct, f"embedded {done}/{total}")

            j.set_progress("embed", 32.0, "embedding knowledge corpus")
            bundle = export_knowledge_bundle(
                corpus_path=corpus,
                output_dir=work / "bundle",
                document_id=doc_id,
                org_id=org_id,
                job_id=j.id,
                filename=fname,
                log=j.log,
                on_progress=on_embed,
            )
            result.update({"corpus_path": str(corpus), **bundle})
            bundle_dir = bundle["output_dir"]
            bundle_type = "knowledge"

        j.set_progress("embed", 80.0, f"bundle ready: {bundle_dir}")

        if upload:
            j.set_progress("upload", 82.0, f"uploading ({mode})")
            up = upload_bundle(
                bundle_dir=bundle_dir,
                mode=mode,  # type: ignore[arg-type]
                org_id=org_id,
                bundle_type=bundle_type,
                log=j.log,
            )
            result["upload"] = dict(up)
            j.set_progress("upload", 98.0, f"upload mode={up['mode']}")

        j.result = result

    return STORE.submit(job, run)


def job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "state": job.state,
        "phase": job.phase,
        "progress": job.progress,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error,
        "result": job.result,
        "logs": job.logs[-200:],
    }
