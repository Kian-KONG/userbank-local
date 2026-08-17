from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

SSH_OPTS = ["-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=10"]
JOB_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Keep in lockstep with scripts/rsync-upload-bundle.sh
VERIFY_PY = """\
import hashlib, json, sys
from pathlib import Path
manifest = json.loads(Path('import.manifest.json').read_text())
shards = manifest.get('embedding_shards') or []
if not shards:
    embedded = manifest.get('files', {}).get('chunks_embedded.jsonl.gz')
    if embedded:
        shards = [{'name': 'chunks_embedded.jsonl.gz', **embedded}]
for shard in shards:
    name = shard['name']
    p = Path(name)
    if not p.is_file():
        print(f'missing shard: {name}', file=sys.stderr)
        sys.exit(1)
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    if h != shard['sha256']:
        print(f'sha256 mismatch {name}: {h} != {shard["sha256"]}', file=sys.stderr)
        sys.exit(1)
    if p.stat().st_size != shard['bytes']:
        print(f'size mismatch {name}', file=sys.stderr)
        sys.exit(1)
for name, entry in manifest.get('files', {}).items():
    if name == 'chunks_embedded.jsonl.gz' and len(shards) > 1:
        continue
    p = Path(name)
    if not p.is_file():
        continue
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    if h != entry['sha256']:
        print(f'sha256 mismatch {name}', file=sys.stderr)
        sys.exit(1)
print('sha256 ok')
"""

DEFAULT_REMOTE_IMPORT_CMD = (
    "docker exec userbank-prod-app-1 node dist/scripts/import-staging-bundle.js --job ${JOB_ID}"
)


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def attach_checksums(manifest: dict[str, Any], bundle_dir: Path) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    shards: list[dict[str, Any]] = []
    embedded = bundle_dir / "chunks.embedded.jsonl.gz"
    if embedded.is_file():
        digest, size = sha256_file(embedded)
        entry = {"sha256": digest, "bytes": size}
        files[embedded.name] = entry
        shards.append({"name": embedded.name, **entry})
    corpus = bundle_dir / "doc_corpus.json"
    if corpus.is_file():
        digest, size = sha256_file(corpus)
        files[corpus.name] = {"sha256": digest, "bytes": size}
    manifest["files"] = files
    manifest["embedding_shards"] = shards
    return manifest


def sanitize_job_id(job_id: str) -> str:
    cleaned = job_id.strip()
    if not JOB_ID_RE.match(cleaned):
        raise RuntimeError(f"invalid job id: {job_id!r}")
    return cleaned


def resolve_import_cmd(template: str, job_id: str) -> str:
    cmd = (template or DEFAULT_REMOTE_IMPORT_CMD).strip() or DEFAULT_REMOTE_IMPORT_CMD
    return cmd.replace("${JOB_ID}", job_id).replace("{job_id}", job_id)


def bundle_size_bytes(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def run_cmd(
    cmd: Sequence[str],
    *,
    stdin: str | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(cmd),
            input=stdin,
            text=True,
            check=True,
            capture_output=capture,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip() or str(exc)
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{detail}") from exc


def ssh_cmd(target: str, remote: str) -> list[str]:
    return ["ssh", *SSH_OPTS, target, remote]


def _parse_avail_kb(stdout: str) -> int:
    token = (stdout or "").strip().split()[-1] if stdout.strip() else "0"
    try:
        return int(token)
    except ValueError:
        return 0


def check_remote_disk(target: str, staging_dir: str, bundle_bytes: int) -> None:
    required_kb = max(1, (bundle_bytes * 2 + 1023) // 1024)
    remote = (
        f"df -k {shlex.quote(staging_dir)} 2>/dev/null | tail -1 | awk '{{print $4}}'"
    )
    try:
        proc = run_cmd(ssh_cmd(target, remote), capture=True)
        avail_kb = _parse_avail_kb(proc.stdout or "")
    except (RuntimeError, OSError):
        avail_kb = 0
    if avail_kb > 0 and avail_kb < required_kb:
        raise RuntimeError(
            f"remote disk insufficient: need {required_kb}KB, avail {avail_kb}KB"
        )


def rsync_upload_bundle(
    bundle_dir: Path,
    job_id: str | None = None,
    org_id: str | None = None,
) -> dict[str, Any]:
    from .config import get_settings

    s = get_settings()
    target = s.ssh_target.strip()
    if not target:
        raise RuntimeError("SSH_TARGET is required for rsync upload")

    bundle_dir = bundle_dir.resolve()
    manifest_path = bundle_dir / "import.manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"missing import.manifest.json in {bundle_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if org_id:
        manifest["org_id"] = org_id
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if "embedding_shards" not in manifest and "files" not in manifest:
        attach_checksums(manifest, bundle_dir)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    resolved_job = sanitize_job_id(str(job_id or manifest.get("job_id") or bundle_dir.name))
    staging = s.import_staging_dir.rstrip("/") or "/data/import-staging"
    remote_dir = f"{staging}/{resolved_job}"
    check_remote_disk(target, staging, bundle_size_bytes(bundle_dir))
    run_cmd(ssh_cmd(target, f"mkdir -p {shlex.quote(remote_dir)}"))

    rsync = [
        "rsync",
        "-av",
        "--progress",
        "--partial",
        "--append-verify",
        "--timeout=600",
        "-e",
        "ssh " + " ".join(SSH_OPTS),
        f"{bundle_dir.as_posix()}/",
        f"{target}:{remote_dir}/",
    ]
    run_cmd(rsync)

    verify_script = (
        "set -euo pipefail\n"
        f"cd {shlex.quote(remote_dir)}\n"
        "python3 - <<'PY'\n"
        f"{VERIFY_PY}"
        "PY\n"
    )
    run_cmd(["ssh", *SSH_OPTS, target, "bash", "-s"], stdin=verify_script)

    import_cmd = resolve_import_cmd(s.remote_import_cmd, resolved_job)
    run_cmd(ssh_cmd(target, import_cmd))
    return {
        "mode": "rsync",
        "job_id": resolved_job,
        "remote_dir": remote_dir,
        "org_id": manifest.get("org_id") or org_id,
    }
