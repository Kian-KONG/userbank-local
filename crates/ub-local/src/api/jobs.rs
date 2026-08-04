use crate::config::settings;
use crate::orchestrate::parse_document;
use crate::pipeline::{ensure_output_subdir, export_knowledge_bundle, upload_bundle};
use chrono::Utc;
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use tokio::sync::Semaphore;
use uuid::Uuid;

#[derive(Debug, Clone, Serialize)]
pub struct Job {
    pub id: String,
    pub kind: String,
    pub state: String,
    pub phase: String,
    pub progress: f32,
    pub created_at: String,
    pub started_at: Option<String>,
    pub finished_at: Option<String>,
    pub error: Option<String>,
    pub result: Option<Value>,
    pub logs: Vec<String>,
}

impl Job {
    pub fn new(kind: &str) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            kind: kind.to_string(),
            state: "pending".into(),
            phase: "queued".into(),
            progress: 0.0,
            created_at: Utc::now().to_rfc3339(),
            started_at: None,
            finished_at: None,
            error: None,
            result: None,
            logs: Vec::new(),
        }
    }

    fn log(&mut self, msg: impl Into<String>) {
        let line = format!("[{}] {}", Utc::now().to_rfc3339(), msg.into());
        self.logs.push(line);
        if self.logs.len() > 2000 {
            let keep = self.logs.split_off(self.logs.len() - 1500);
            self.logs = keep;
        }
    }

    fn set_progress(&mut self, phase: &str, progress: f32, msg: Option<&str>) {
        self.phase = phase.to_string();
        self.progress = progress.clamp(0.0, 100.0);
        if let Some(m) = msg {
            self.log(format!("[{phase} {:.0}%] {m}", self.progress));
        }
    }
}

#[derive(Clone)]
pub struct JobStore {
    inner: Arc<Mutex<HashMap<String, Job>>>,
    limit: Arc<Semaphore>,
}

impl JobStore {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(HashMap::new())),
            limit: Arc::new(Semaphore::new(2)),
        }
    }

    pub fn get(&self, id: &str) -> Option<Job> {
        self.inner.lock().ok()?.get(id).cloned()
    }

    pub fn upsert(&self, job: Job) {
        if let Ok(mut g) = self.inner.lock() {
            g.insert(job.id.clone(), job);
        }
    }

    pub fn mutate<F: FnOnce(&mut Job)>(&self, id: &str, f: F) {
        if let Ok(mut g) = self.inner.lock() {
            if let Some(job) = g.get_mut(id) {
                f(job);
            }
        }
    }

    pub fn start_pipeline(
        &self,
        input: PathBuf,
        track: String,
        mode: String,
        upload: bool,
        skip_mineru: bool,
        org_id: Option<String>,
        document_id: Option<String>,
        filename: Option<String>,
    ) -> Job {
        let mut job = Job::new("pipeline");
        let id = job.id.clone();
        let id_for_return = id.clone();
        self.upsert(job.clone());
        let store = self.clone();
        let permit_sem = self.limit.clone();
        tokio::spawn(async move {
            let _permit = permit_sem.acquire().await.ok();
            store.mutate(&id, |j| {
                j.state = "running".into();
                j.started_at = Some(Utc::now().to_rfc3339());
                j.set_progress("parse", 5.0, Some("starting pipeline"));
            });
            let result = run_pipeline(
                &store,
                &id,
                &input,
                &track,
                &mode,
                upload,
                skip_mineru,
                org_id.as_deref(),
                document_id.as_deref(),
                filename.as_deref(),
            )
            .await;
            store.mutate(&id, |j| {
                j.finished_at = Some(Utc::now().to_rfc3339());
                match result {
                    Ok(v) => {
                        j.state = "done".into();
                        j.result = Some(v);
                        j.set_progress("done", 100.0, Some("finished"));
                    }
                    Err(e) => {
                        j.state = "failed".into();
                        j.phase = "failed".into();
                        j.error = Some(e.to_string());
                        j.log(e.to_string());
                    }
                }
            });
        });
        self.get(&id_for_return).unwrap_or(job)
    }
}

async fn run_pipeline(
    store: &JobStore,
    job_id: &str,
    input: &Path,
    track: &str,
    mode: &str,
    upload: bool,
    skip_mineru: bool,
    org_id: Option<&str>,
    document_id: Option<&str>,
    filename: Option<&str>,
) -> anyhow::Result<Value> {
    let _ = track; // survey track: same export path for now when corpus-like
    let work = ensure_output_subdir(&format!("jobs/{job_id}"));
    store.mutate(job_id, |j| j.set_progress("parse", 10.0, Some("parsing")));
    let corpus = parse_document(input, &work.join("parse"), skip_mineru)?;
    store.mutate(job_id, |j| {
        j.set_progress("embed", 35.0, Some("export + embed"));
    });
    let doc_id = document_id.unwrap_or("local-doc");
    let export_dir = work.join("bundle");
    let store2 = store.clone();
    let jid = job_id.to_string();
    let export = export_knowledge_bundle(
        &corpus,
        &export_dir,
        doc_id,
        filename,
        org_id,
        Some(Box::new(move |done, total| {
            let pct = 35.0 + 50.0 * (done as f32 / total.max(1) as f32);
            store2.mutate(&jid, |j| {
                j.set_progress("embed", pct, Some(&format!("embedded {done}/{total}")));
            });
        })),
    )
    .await?;

    if !upload {
        return Ok(json!({ "export": export, "uploaded": false }));
    }
    store.mutate(job_id, |j| j.set_progress("upload", 90.0, Some("uploading")));
    let uploaded = upload_bundle(&export_dir, mode, org_id, None).await?;
    Ok(json!({ "export": export, "upload": uploaded }))
}

pub async fn health_payload() -> Value {
    let s = settings();
    json!({
        "ok": true,
        "host": s.ub_local_host,
        "port": s.ub_local_port,
        "rag": crate::rag::rag_ready().await,
        "mineru": crate::orchestrate::check_mineru(),
        "deepread": crate::orchestrate::check_deepread(),
        "ssh_configured": !s.ssh_target.trim().is_empty(),
        "org_id": s.survey_org_id,
        "api_url": s.userbank_api_url,
        "work_dir": s.work_dir().display().to_string(),
    })
}
