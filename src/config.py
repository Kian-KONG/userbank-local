from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
    )

    rag_service_url: str = "http://127.0.0.1:8760"
    rag_internal_secret: str = ""
    embedding_model: str = "qwen3-embedding:0.6b"
    vector_store_dimension: int = 1024

    userbank_api_url: str = "http://127.0.0.1:3000"
    survey_org_id: str = "local-dev-eb"
    survey_import_secret: str = ""

    ssh_target: str = ""
    import_staging_dir: str = "/data/import-staging"
    upload_rsync_min_bytes: int = 52_428_800
    upload_batch_size: int = 500
    upload_http_retries: int = 3

    mineru_dir: str = ""
    deepread_dir: str = ""
    mineru_python: str = "python3"

    ub_local_host: str = "127.0.0.1"
    ub_local_port: int = 8780
    ub_local_work_dir: str = "./output"

    @property
    def root(self) -> Path:
        return Path.cwd()

    def work_dir(self) -> Path:
        p = Path(self.ub_local_work_dir)
        abs_path = p if p.is_absolute() else self.root / p
        abs_path.mkdir(parents=True, exist_ok=True)
        return abs_path

    def mineru_path(self) -> Path:
        if self.mineru_dir.strip():
            return Path(self.mineru_dir)
        return (self.root.parent / "MinerU").resolve()

    def deepread_path(self) -> Path:
        if self.deepread_dir.strip():
            return Path(self.deepread_dir)
        return (self.root.parent / "DeepRead").resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def path_exists(path: Path) -> bool:
    return path.exists()
