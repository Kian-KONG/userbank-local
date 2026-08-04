use std::env;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

#[derive(Debug, Clone)]
pub struct Settings {
    pub rag_service_url: String,
    pub rag_internal_secret: String,
    pub embedding_model: String,
    pub vector_store_dimension: usize,
    pub userbank_api_url: String,
    pub survey_org_id: String,
    pub survey_import_secret: String,
    pub ssh_target: String,
    pub import_staging_dir: String,
    pub upload_rsync_min_bytes: u64,
    pub upload_batch_size: usize,
    pub upload_http_retries: usize,
    pub mineru_dir: String,
    pub deepread_dir: String,
    pub mineru_python: String,
    pub ub_local_host: String,
    pub ub_local_port: u16,
    pub ub_local_work_dir: String,
    pub root: PathBuf,
}

impl Settings {
    pub fn from_env() -> Self {
        let root = env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        Self {
            rag_service_url: env_str("RAG_SERVICE_URL", "http://127.0.0.1:8760"),
            rag_internal_secret: env_str("RAG_INTERNAL_SECRET", ""),
            embedding_model: env_str("EMBEDDING_MODEL", "qwen3-embedding:0.6b"),
            vector_store_dimension: env_parse("VECTOR_STORE_DIMENSION", 1024_usize),
            userbank_api_url: env_str("USERBANK_API_URL", "http://127.0.0.1:3000"),
            survey_org_id: env_str("SURVEY_ORG_ID", "local-dev-eb"),
            survey_import_secret: env_str("SURVEY_IMPORT_SECRET", ""),
            ssh_target: env_str("SSH_TARGET", ""),
            import_staging_dir: env_str("IMPORT_STAGING_DIR", "/data/import-staging"),
            upload_rsync_min_bytes: env_parse("UPLOAD_RSYNC_MIN_BYTES", 52_428_800_u64),
            upload_batch_size: env_parse("UPLOAD_BATCH_SIZE", 500_usize),
            upload_http_retries: env_parse("UPLOAD_HTTP_RETRIES", 3_usize),
            mineru_dir: env_str("MINERU_DIR", ""),
            deepread_dir: env_str("DEEPREAD_DIR", ""),
            mineru_python: env_str("MINERU_PYTHON", "python3"),
            ub_local_host: env_str("UB_LOCAL_HOST", "127.0.0.1"),
            ub_local_port: env_parse("UB_LOCAL_PORT", 8780_u16),
            ub_local_work_dir: env_str("UB_LOCAL_WORK_DIR", "./output"),
            root,
        }
    }

    pub fn work_dir(&self) -> PathBuf {
        let p = PathBuf::from(&self.ub_local_work_dir);
        let abs = if p.is_absolute() {
            p
        } else {
            self.root.join(p)
        };
        let _ = std::fs::create_dir_all(&abs);
        abs
    }

    pub fn mineru_path(&self) -> PathBuf {
        if self.mineru_dir.trim().is_empty() {
            self.root.parent().unwrap_or(&self.root).join("MinerU")
        } else {
            PathBuf::from(&self.mineru_dir)
        }
    }

    pub fn deepread_path(&self) -> PathBuf {
        if self.deepread_dir.trim().is_empty() {
            self.root.parent().unwrap_or(&self.root).join("DeepRead")
        } else {
            PathBuf::from(&self.deepread_dir)
        }
    }
}

pub fn settings() -> &'static Settings {
    static S: OnceLock<Settings> = OnceLock::new();
    S.get_or_init(Settings::from_env)
}

fn env_str(key: &str, default: &str) -> String {
    env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_parse<T: std::str::FromStr>(key: &str, default: T) -> T {
    env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}

pub fn path_exists(p: &Path) -> bool {
    p.exists()
}
