from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
SIBLING_ROOT = ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.pipeline"),
        env_file_encoding="utf-8",
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
    bundle_shard_max_bytes: int = 83_886_080
    upload_batch_size: int = 500
    upload_http_retries: int = 3

    mineru_dir: str = ""
    deepread_dir: str = ""
    mineru_python: str = "python3"
    mineru_backend: str = "vlm-http-client"
    mineru_api_url: str = "http://127.0.0.1:8757"

    ub_local_host: str = "127.0.0.1"
    ub_local_port: int = 8780
    ub_local_work_dir: str = "./output"

    def resolved_mineru_dir(self) -> Path:
        if self.mineru_dir.strip():
            return Path(self.mineru_dir).expanduser().resolve()
        return (SIBLING_ROOT / "MinerU").resolve()

    def resolved_deepread_dir(self) -> Path:
        if self.deepread_dir.strip():
            return Path(self.deepread_dir).expanduser().resolve()
        return (SIBLING_ROOT / "DeepRead").resolve()

    def work_dir(self) -> Path:
        p = Path(self.ub_local_work_dir).expanduser()
        if not p.is_absolute():
            p = ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p.resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
