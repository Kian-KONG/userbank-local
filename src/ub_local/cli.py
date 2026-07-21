from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
import uvicorn

from ub_local.config import get_settings
from ub_local.orchestrate.parse import parse_document
from ub_local.pipeline.export_knowledge import export_knowledge_bundle
from ub_local.pipeline.upload import upload_bundle
from ub_local.pipeline.types import UploadMode

app = typer.Typer(add_completion=False, no_args_is_help=True, help="userbank-local CLI")


@app.command("serve")
def serve(
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> None:
    """Start FastAPI control plane (localhost)."""
    settings = get_settings()
    uvicorn.run(
        "ub_local.api.app:app",
        host=host or settings.ub_local_host,
        port=port or settings.ub_local_port,
        reload=False,
    )


@app.command("parse")
def parse_cmd(
    input_path: Path = typer.Argument(...),
    out: Path = typer.Option(None, "--out", help="Work directory"),
    skip_mineru: bool = typer.Option(False, "--skip-mineru"),
) -> None:
    settings = get_settings()
    work = out or settings.work_dir() / "cli-parse"
    corpus = parse_document(input_path, work, skip_mineru=skip_mineru)
    typer.echo(corpus)


@app.command("export")
def export_cmd(
    corpus: Path = typer.Option(..., "--corpus"),
    output_dir: Path = typer.Option(..., "--output-dir"),
    document_id: str = typer.Option("local-doc", "--document-id"),
    filename: Optional[str] = typer.Option(None, "--filename"),
    org: Optional[str] = typer.Option(None, "--org"),
) -> None:
    result = export_knowledge_bundle(
        corpus_path=corpus,
        output_dir=output_dir,
        document_id=document_id,
        filename=filename,
        org_id=org,
    )
    typer.echo(result["output_dir"])


@app.command("upload")
def upload_cmd(
    bundle_dir: Path = typer.Option(..., "--bundle-dir"),
    mode: UploadMode = typer.Option("auto", "--mode"),
    org: Optional[str] = typer.Option(None, "--org"),
    api: Optional[str] = typer.Option(None, "--api"),
) -> None:
    result = upload_bundle(
        bundle_dir=bundle_dir, mode=mode, org_id=org, api_url=api
    )
    typer.echo(f"upload complete mode={result['mode']}")


if __name__ == "__main__":
    app()
