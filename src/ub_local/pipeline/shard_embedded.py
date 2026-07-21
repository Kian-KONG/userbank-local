from __future__ import annotations

import gzip
from pathlib import Path

from ub_local.config import get_settings
from ub_local.pipeline.embedded_jsonl import build_staging_file_entry
from ub_local.pipeline.paths import CHUNKS_EMBEDDED_FILENAME, embedded_shard_filename


def _max_uncompressed(max_compressed: int) -> int:
    return max_compressed * 2


def shard_embedded_gz(
    embedded_path: Path,
    output_dir: Path | None = None,
    *,
    max_bytes: int | None = None,
    remove_original: bool = True,
) -> list[dict]:
    settings = get_settings()
    dir_ = output_dir or embedded_path.parent
    limit = max_bytes if max_bytes is not None else settings.bundle_shard_max_bytes
    uncompressed_limit = _max_uncompressed(limit)

    shards: list[dict] = []
    shard_index = 0
    buffer: list[str] = []
    buffer_bytes = 0

    def flush() -> None:
        nonlocal shard_index, buffer, buffer_bytes
        if not buffer:
            return
        name = embedded_shard_filename(shard_index)
        path = dir_ / name
        with gzip.open(path, "wt", encoding="utf-8") as f:
            for line in buffer:
                f.write(line + "\n")
        entry = build_staging_file_entry(path)
        shards.append({"name": name, "index": shard_index, **entry})
        shard_index += 1
        buffer = []
        buffer_bytes = 0

    with gzip.open(embedded_path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            line_bytes = len(line.encode("utf-8")) + 1
            if buffer_bytes > 0 and buffer_bytes + line_bytes > uncompressed_limit:
                flush()
            buffer.append(line)
            buffer_bytes += line_bytes
    flush()

    if not shards:
        raise RuntimeError(f"no shards produced from {embedded_path}")

    if len(shards) == 1 and shards[0]["name"] != CHUNKS_EMBEDDED_FILENAME:
        single = shards[0]
        target = dir_ / CHUNKS_EMBEDDED_FILENAME
        (dir_ / single["name"]).rename(target)
        entry = build_staging_file_entry(target)
        return [{"name": CHUNKS_EMBEDDED_FILENAME, "index": 0, **entry}]

    if remove_original and len(shards) > 1:
        embedded_path.unlink(missing_ok=True)

    return shards


def maybe_shard_embedded_bundle(
    bundle_dir: Path, *, max_bytes: int | None = None
) -> list[dict] | None:
    embedded = bundle_dir / CHUNKS_EMBEDDED_FILENAME
    shards = shard_embedded_gz(
        embedded, bundle_dir, max_bytes=max_bytes, remove_original=True
    )
    if len(shards) <= 1:
        return None
    return shards
