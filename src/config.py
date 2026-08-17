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

    # Prefer OpenAI-compatible local embed (8756). If empty, fall back to userbank-rag.
    embed_base_url: str = "http://127.0.0.1:8756/v1"
    embed_api_key: str = "local"
    embedding_model: str = "qwen3-embedding-8b"
    vector_store_dimension: int = 4096

    # Legacy userbank-rag sidecar (optional)
    rag_service_url: str = "http://127.0.0.1:8760"
    rag_internal_secret: str = ""

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
    mineru_python: str = ""
    deepread_python: str = ""
    mineru_backend: str = "vlm-engine"
    mineru_effort: str = "high"
    mineru_api_url: str = "http://127.0.0.1:8757"
    mineru_model_source: str = "local"
    mineru_page_chunk_size: int = 50
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
