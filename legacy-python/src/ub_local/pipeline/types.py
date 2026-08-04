from __future__ import annotations

from typing import Any, Literal, TypedDict

DEFAULT_EMBED_BATCH_SIZE = 32
DEFAULT_UPLOAD_BATCH_SIZE = 500

UploadMode = Literal["http", "rsync", "auto"]
BundleType = Literal["knowledge", "survey"]


class FlatChunk(TypedDict):
    id: str
    text: str
    metadata: dict[str, Any]


class EmbeddedChunk(FlatChunk):
    embedding: list[float]


class StagingFileEntry(TypedDict):
    sha256: str
    bytes: int


class EmbeddingShardEntry(StagingFileEntry):
    name: str
    index: int
