from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import uvicorn

from .config import get_settings
from .orchestrate import parse_document
from .pipeline import ensure_output_subdir, export_knowledge_bundle, upload_bundle
from .api import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="ub-local", description="userbank-local CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start local control plane")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    parse = sub.add_parser("parse", help="Parse document to corpus JSON")
    parse.add_argument("input", type=Path)
    parse.add_argument("--out", type=Path, default=None)
    parse.add_argument("--skip-mineru", action="store_true")
    parse.add_argument(
        "--no-formula",
        action="store_true",
        help="Skip MinerU formula parsing (faster when the PDF has no math)",
    )
    parse.add_argument(
        "--no-table",
        action="store_true",
        help="Skip MinerU table parsing (rarely useful; tables stay on by default)",
    )

    export = sub.add_parser("export", help="Export knowledge bundle (flatten + embed)")
    export.add_argument("--corpus", type=Path, required=True)
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--document-id", default="local-doc")
    export.add_argument("--filename", default=None)
    export.add_argument("--org", default=None)

    upload = sub.add_parser("upload", help="rsync bundle to ECS and trigger server import")
    upload.add_argument("--bundle-dir", type=Path, required=True)
    upload.add_argument("--org", default=None)
    upload.add_argument("--job-id", default=None)

    args = parser.parse_args()
    if args.command == "serve":
        s = get_settings()
        host = args.host or s.ub_local_host
        port = args.port or s.ub_local_port
        uvicorn.run(create_app(), host=host, port=port, log_level="info")
        return

    if args.command == "parse":
        work = args.out or ensure_output_subdir("cli-parse")
        corpus = parse_document(
            args.input,
            work,
            args.skip_mineru,
            formula=False if args.no_formula else None,
            table=False if args.no_table else None,
        )
        print(corpus)
        return

    if args.command == "export":
        result = asyncio.run(
            export_knowledge_bundle(
                args.corpus,
                args.output_dir,
                args.document_id,
                args.filename,
                args.org,
                None,
            )
        )
        print(result["output_dir"])
        return

    if args.command == "upload":
        result = asyncio.run(
            upload_bundle(args.bundle_dir, args.org, job_id=args.job_id)
        )
        print(f"upload complete mode={result.get('mode', 'rsync')} job={result.get('job_id', '?')}")
        return


if __name__ == "__main__":
    main()
