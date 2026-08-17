from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
    )

    # Same contract as userbank-rag / userbank-api import (0.6B Q8_0, dim 1024).
    # Empty embed_base_url → userbank-rag sidecar. Do not point this at DeepRead 8B.
    embed_base_url: str = ""
    embed_api_key: str = "local"
    embedding_model: str = "qwen3-embedding:0.6b"
    vector_store_dimension: int = 1024

    # Legacy userbank-rag sidecar (optional)
    rag_service_url: str = "http://127.0.0.1:8760"
    rag_internal_secret: str = ""

    survey_org_id: str = "local-dev-eb"

    ssh_target: str = ""
    import_staging_dir: str = "/data/import-staging"
    remote_import_cmd: str = (
        "docker exec userbank-prod-app-1 node dist/scripts/import-staging-bundle.js --job ${JOB_ID}"
    )

    mineru_dir: str = ""
    deepread_dir: str = ""
    mineru_python: str = ""
    deepread_python: str = ""
    mineru_backend: str = "vlm-engine"
    mineru_effort: str = "high"
    mineru_api_url: str = "http://127.0.0.1:8757"
    mineru_model_source: str = "local"
    mineru_page_chunk_size: int = 128
    mineru_formula: bool = True
    mineru_table: bool = True
    mineru_task_timeout_seconds: float = 7200

    ub_local_host: str = "127.0.0.1"
    ub_local_port: int = 8780
    ub_local_work_dir: str = "./output"

    llm_api_url: str = "https://aigc.bosch.com.cn/llmservice/api/v1/chat/completions"
    llm_api_key: str = ""
    llm_synth_model: str = "qwen3.7-max"
    vision_page_scale: float = 2.0
    synth_page_summary_chars: int = 400

    @property
    def root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def work_dir(self) -> Path:
        p = Path(self.ub_local_work_dir)
        abs_path = p if p.is_absolute() else self.root / p
        abs_path.mkdir(parents=True, exist_ok=True)
        return abs_path

    def mineru_path(self) -> Path:
        if self.mineru_dir.strip():
            return Path(self.mineru_dir).expanduser().resolve()
        return (self.root.parent / "MinerU").resolve()

    def deepread_path(self) -> Path:
        if self.deepread_dir.strip():
            return Path(self.deepread_dir).expanduser().resolve()
        return (self.root.parent / "DeepRead").resolve()

    def resolved_mineru_python(self) -> str:
        if self.mineru_python.strip():
            return self.mineru_python
        candidate = self.mineru_path() / ".venv" / "bin" / "python"
        return str(candidate) if candidate.exists() else "python3"

    def resolved_deepread_python(self) -> str:
        if self.deepread_python.strip():
            return self.deepread_python
        candidate = self.deepread_path() / ".venv" / "bin" / "python"
        return str(candidate) if candidate.exists() else "python3"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def path_exists(path: Path) -> bool:
    return path.exists()
