pub mod jobs;

use crate::api::jobs::{health_payload, Job, JobStore};
use crate::config::settings;
use axum::extract::{Multipart, Path, State};
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::Deserialize;
use serde_json::json;
use std::path::PathBuf;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;

#[derive(Clone)]
pub struct AppState {
    pub jobs: JobStore,
}

pub fn app(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/jobs/{id}", get(get_job))
        .route("/jobs/parse", post(jobs_parse))
        .route("/jobs/export", post(jobs_export))
        .route("/jobs/upload", post(jobs_upload))
        .route("/jobs/pipeline", post(jobs_pipeline))
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http())
        .with_state(state)
}

async fn health(State(_): State<AppState>) -> impl IntoResponse {
    Json(health_payload().await)
}

async fn get_job(State(state): State<AppState>, Path(id): Path<String>) -> impl IntoResponse {
    match state.jobs.get(&id) {
        Some(job) => Json(job).into_response(),
        None => (
            StatusCode::NOT_FOUND,
            Json(json!({ "error": "job not found" })),
        )
            .into_response(),
    }
}

#[derive(Deserialize)]
struct ExportBody {
    corpus_path: String,
    document_id: Option<String>,
    filename: Option<String>,
    org_id: Option<String>,
}

#[derive(Deserialize)]
struct UploadBody {
    bundle_dir: String,
    mode: Option<String>,
    org_id: Option<String>,
}

async fn jobs_parse(
    State(state): State<AppState>,
    mut multipart: Multipart,
) -> impl IntoResponse {
    let mut path: Option<PathBuf> = None;
    let mut skip_mineru = false;
    while let Ok(Some(field)) = multipart.next_field().await {
        let name = field.name().unwrap_or("").to_string();
        if name == "file" {
            let filename = field
                .file_name()
                .unwrap_or("upload.bin")
                .to_string();
            let data = field.bytes().await.unwrap_or_default();
            let dest = settings().work_dir().join("uploads").join(&filename);
            let _ = std::fs::create_dir_all(dest.parent().unwrap());
            if std::fs::write(&dest, &data).is_ok() {
                path = Some(dest);
            }
        } else if name == "path" {
            if let Ok(text) = field.text().await {
                path = Some(PathBuf::from(text));
            }
        } else if name == "skip_mineru" {
            if let Ok(text) = field.text().await {
                skip_mineru = matches!(text.as_str(), "1" | "true" | "yes");
            }
        }
    }
    let Some(input) = path else {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({ "error": "file or path required" })),
        )
            .into_response();
    };
    let job = state.jobs.start_pipeline(
        input,
        "knowledge".into(),
        "http".into(),
        false,
        skip_mineru,
        None,
        None,
        None,
    );
    Json(job).into_response()
}

async fn jobs_export(
    State(state): State<AppState>,
    Json(body): Json<ExportBody>,
) -> impl IntoResponse {
    let job = state.jobs.start_pipeline(
        PathBuf::from(body.corpus_path),
        "knowledge".into(),
        "http".into(),
        false,
        true,
        body.org_id,
        body.document_id,
        body.filename,
    );
    Json(job)
}

async fn jobs_upload(
    State(state): State<AppState>,
    Json(body): Json<UploadBody>,
) -> impl IntoResponse {
    // Run upload inline as a short job via pipeline helper path.
    let bundle = PathBuf::from(body.bundle_dir);
    let mode = body.mode.unwrap_or_else(|| "auto".into());
    let org = body.org_id;
    let mut job = Job::new("upload");
    let id = job.id.clone();
    let id_ret = id.clone();
    state.jobs.upsert(job.clone());
    let store = state.jobs.clone();
    tokio::spawn(async move {
        store.mutate(&id, |j| {
            j.state = "running".into();
            j.started_at = Some(chrono::Utc::now().to_rfc3339());
        });
        match crate::pipeline::upload_bundle(&bundle, &mode, org.as_deref(), None).await {
            Ok(v) => store.mutate(&id, |j| {
                j.state = "done".into();
                j.result = Some(v);
                j.phase = "done".into();
                j.progress = 100.0;
                j.finished_at = Some(chrono::Utc::now().to_rfc3339());
            }),
            Err(e) => store.mutate(&id, |j| {
                j.state = "failed".into();
                j.error = Some(e.to_string());
                j.finished_at = Some(chrono::Utc::now().to_rfc3339());
            }),
        }
    });
    Json(store_get(&state, &id_ret))
}

fn store_get(state: &AppState, id: &str) -> Job {
    state.jobs.get(id).unwrap_or_else(|| Job::new("upload"))
}

async fn jobs_pipeline(
    State(state): State<AppState>,
    mut multipart: Multipart,
) -> impl IntoResponse {
    let mut path: Option<PathBuf> = None;
    let mut track = "knowledge".to_string();
    let mut mode = "auto".to_string();
    let mut upload = true;
    let mut skip_mineru = false;
    let mut org_id: Option<String> = None;
    let mut document_id: Option<String> = None;
    let mut filename: Option<String> = None;

    while let Ok(Some(field)) = multipart.next_field().await {
        let name = field.name().unwrap_or("").to_string();
        match name.as_str() {
            "file" => {
                let fname = field.file_name().unwrap_or("upload.bin").to_string();
                filename = filename.or(Some(fname.clone()));
                let data = field.bytes().await.unwrap_or_default();
                let dest = settings().work_dir().join("uploads").join(&fname);
                let _ = std::fs::create_dir_all(dest.parent().unwrap());
                if std::fs::write(&dest, &data).is_ok() {
                    path = Some(dest);
                }
            }
            "path" => {
                if let Ok(text) = field.text().await {
                    path = Some(PathBuf::from(text));
                }
            }
            "track" => {
                if let Ok(text) = field.text().await {
                    track = text;
                }
            }
            "mode" => {
                if let Ok(text) = field.text().await {
                    mode = text;
                }
            }
            "upload" => {
                if let Ok(text) = field.text().await {
                    upload = !matches!(text.as_str(), "0" | "false" | "no");
                }
            }
            "skip_mineru" => {
                if let Ok(text) = field.text().await {
                    skip_mineru = matches!(text.as_str(), "1" | "true" | "yes");
                }
            }
            "org_id" => {
                if let Ok(text) = field.text().await {
                    org_id = Some(text);
                }
            }
            "document_id" => {
                if let Ok(text) = field.text().await {
                    document_id = Some(text);
                }
            }
            "filename" => {
                if let Ok(text) = field.text().await {
                    filename = Some(text);
                }
            }
            _ => {}
        }
    }

    let Some(input) = path else {
        return (
            StatusCode::BAD_REQUEST,
            Json(json!({ "error": "file or path required" })),
        )
            .into_response();
    };

    let job = state.jobs.start_pipeline(
        input,
        track,
        mode,
        upload,
        skip_mineru,
        org_id,
        document_id,
        filename,
    );
    Json(job).into_response()
}
