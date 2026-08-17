import gzip
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.rsync_upload import (
    attach_checksums,
    resolve_import_cmd,
    rsync_upload_bundle,
    sanitize_job_id,
    sha256_file,
)


def _settings(**overrides):
    base = {
        "ssh_target": "deploy@ecs-host",
        "import_staging_dir": "/data/import-staging",
        "remote_import_cmd": (
            "docker exec userbank-prod-app-1 node dist/scripts/import-staging-bundle.js --job ${JOB_ID}"
        ),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _write_gz(path: Path, lines: list[dict]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for item in lines:
            fh.write(json.dumps(item) + "\n")


def test_sha256_file_matches_hashlib(tmp_path: Path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"hello-rsync")
    digest, size = sha256_file(p)
    assert size == 11
    assert digest == hashlib.sha256(b"hello-rsync").hexdigest()


def test_attach_checksums_writes_shards_and_files(tmp_path: Path):
    _write_gz(tmp_path / "chunks.embedded.jsonl.gz", [{"id": "a", "text": "t", "embedding": [0.1]}])
    (tmp_path / "doc_corpus.json").write_text("{}\n", encoding="utf-8")
    manifest = attach_checksums({"document_id": "doc"}, tmp_path)
    shard = manifest["embedding_shards"][0]
    assert shard["name"] == "chunks.embedded.jsonl.gz"
    assert shard["bytes"] > 0
    assert shard["sha256"] == sha256_file(tmp_path / "chunks.embedded.jsonl.gz")[0]
    assert manifest["files"]["chunks.embedded.jsonl.gz"]["sha256"] == shard["sha256"]
    assert "doc_corpus.json" in manifest["files"]


def test_sanitize_job_id_rejects_shell_meta():
    assert sanitize_job_id("abc-123") == "abc-123"
    with pytest.raises(RuntimeError):
        sanitize_job_id("foo; rm -rf /")


def test_resolve_import_cmd_substitutes_job_id():
    cmd = resolve_import_cmd(
        "docker exec userbank-prod-app-1 node dist/scripts/import-staging-bundle.js --job ${JOB_ID}",
        "job-1",
    )
    assert cmd.endswith("--job job-1")


def test_rsync_upload_bundle_runs_ssh_rsync_verify_import(tmp_path: Path, monkeypatch):
    _write_gz(tmp_path / "chunks.embedded.jsonl.gz", [{"id": "a", "text": "t", "embedding": [0.1]}])
    (tmp_path / "doc_corpus.json").write_text("{}\n", encoding="utf-8")
    manifest = attach_checksums(
        {"job_id": "job-9", "org_id": "org-1", "filename": "doc.json"},
        tmp_path,
    )
    (tmp_path / "import.manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(cmd, *, stdin=None, capture=False):
        del stdin
        calls.append(list(cmd))
        stdout = "999999\n" if capture else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("src.config.get_settings", lambda: _settings())
    monkeypatch.setattr("src.rsync_upload.run_cmd", fake_run)

    result = rsync_upload_bundle(tmp_path, job_id="job-9")
    assert result["mode"] == "rsync"
    assert result["job_id"] == "job-9"
    assert result["remote_dir"] == "/data/import-staging/job-9"

    rsync = next(c for c in calls if c[0] == "rsync")
    assert "-z" not in rsync
    assert "--partial" in rsync
    assert "--append-verify" in rsync
    assert rsync[-1] == "deploy@ecs-host:/data/import-staging/job-9/"
    assert any(c[0] == "ssh" and "mkdir -p" in c[-1] for c in calls)
    assert any(c[-2:] == ["bash", "-s"] for c in calls)
    assert any(c[0] == "ssh" and "import-staging-bundle.js" in c[-1] for c in calls)


def test_rsync_upload_requires_ssh_target(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("src.config.get_settings", lambda: _settings(ssh_target=""))
    (tmp_path / "import.manifest.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="SSH_TARGET"):
        rsync_upload_bundle(tmp_path)
