mod flatten;

use crate::config::settings;
use crate::pipeline::flatten::flatten_corpus;
use crate::rag::rag_embed;
use anyhow::{anyhow, Context, Result};
use flate2::write::GzEncoder;
use flate2::Compression;
use serde_json::{json, Value};
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use uuid::Uuid;

const BATCH: usize = 16;

pub async fn export_knowledge_bundle(
    corpus_path: &Path,
    output_dir: &Path,
    document_id: &str,
    filename: Option<&str>,
    org_id: Option<&str>,
    mut on_progress: Option<Box<dyn FnMut(usize, usize) + Send>>,
) -> Result<Value> {
    let s = settings();
    fs::create_dir_all(output_dir)?;
    let corpus: Value = serde_json::from_str(&fs::read_to_string(corpus_path)?)
        .context("parse corpus json")?;
    let flat = flatten_corpus(&corpus, document_id);
    if flat.is_empty() {
        return Err(anyhow!("corpus produced no embeddable paragraphs"));
    }

    fs::write(
        output_dir.join("doc_corpus.json"),
        serde_json::to_string_pretty(&corpus)? + "\n",
    )?;

    let mut embedded_items = Vec::new();
    let total = flat.len();
    for chunk in flat.chunks(BATCH) {
        let texts: Vec<String> = chunk.iter().map(|c| c.text.clone()).collect();
        let vectors = rag_embed(&texts, "document").await?;
        for (item, vector) in chunk.iter().zip(vectors.into_iter()) {
            embedded_items.push(json!({
                "id": item.id,
                "text": item.text,
                "embedding": vector,
                "metadata": item.metadata,
            }));
            if let Some(cb) = on_progress.as_mut() {
                cb(embedded_items.len(), total);
            }
        }
    }

    let embedded_path = output_dir.join("chunks.embedded.jsonl.gz");
    write_jsonl_gz(&embedded_path, &embedded_items)?;

    let resolved_org = org_id.unwrap_or(&s.survey_org_id);
    let fname = filename
        .map(|s| s.to_string())
        .unwrap_or_else(|| {
            corpus_path
                .file_name()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_else(|| "document.json".into())
        });

    let manifest = json!({
        "embedding_model": s.embedding_model,
        "dimensions": s.vector_store_dimension,
        "filename": fname,
        "document_id": document_id,
        "batch_index": 0,
        "total_batches": 1,
        "reset_document": true,
        "org_id": resolved_org,
        "job_id": Uuid::new_v4().to_string(),
        "chunk_count": embedded_items.len(),
    });
    fs::write(
        output_dir.join("import.manifest.json"),
        serde_json::to_string_pretty(&manifest)? + "\n",
    )?;

    Ok(json!({
        "output_dir": output_dir.display().to_string(),
        "document_id": document_id,
        "chunk_count": embedded_items.len(),
        "org_id": resolved_org,
    }))
}

fn write_jsonl_gz(path: &Path, items: &[Value]) -> Result<()> {
    let file = File::create(path)?;
    let mut enc = GzEncoder::new(file, Compression::default());
    for item in items {
        writeln!(enc, "{}", serde_json::to_string(item)?)?;
    }
    enc.finish()?;
    Ok(())
}

pub async fn upload_bundle(
    bundle_dir: &Path,
    mode: &str,
    org_id: Option<&str>,
    api_url: Option<&str>,
) -> Result<Value> {
    let s = settings();
    let org = org_id.unwrap_or(&s.survey_org_id);
    let api = api_url.unwrap_or(&s.userbank_api_url).trim_end_matches('/');
    let secret = s.survey_import_secret.trim();
    if secret.is_empty() {
        return Err(anyhow!("SURVEY_IMPORT_SECRET is required for upload"));
    }

    let manifest: Value = serde_json::from_str(&fs::read_to_string(
        bundle_dir.join("import.manifest.json"),
    )?)?;
    let embedded_path = bundle_dir.join("chunks.embedded.jsonl.gz");
    let chunks = read_jsonl_gz(&embedded_path)?;

    let import_path = resolve_knowledge_import_path(api);
    let payload = json!({
        "manifest": manifest,
        "chunks": chunks.iter().map(|c| json!({
            "id": c.get("id"),
            "text": c.get("text"),
            "embedding": c.get("embedding"),
            "metadata": c.get("metadata").cloned().unwrap_or(json!({})),
        })).collect::<Vec<_>>(),
    });

    let use_http = mode == "http"
        || (mode == "auto" && dir_size(bundle_dir)? < s.upload_rsync_min_bytes);
    if !use_http {
        return Err(anyhow!(
            "rsync mode not implemented in Rust binary yet; use --mode http or smaller bundles"
        ));
    }

    let url = format!("{api}{import_path}?groupId={}", urlencoding_group(org));
    let mut last_err = None;
    for attempt in 0..=s.upload_http_retries {
        let resp = reqwest::Client::new()
            .post(&url)
            .header("Content-Type", "application/json")
            .header("x-survey-import-secret", secret)
            .json(&payload)
            .timeout(std::time::Duration::from_secs(300))
            .send()
            .await;
        match resp {
            Ok(r) if r.status().is_success() => {
                let body: Value = r.json().await.unwrap_or(json!({ "ok": true }));
                return Ok(json!({ "mode": "http", "result": body }));
            }
            Ok(r) => {
                let status = r.status();
                let text = r.text().await.unwrap_or_default();
                last_err = Some(anyhow!("HTTP {status}: {text}"));
            }
            Err(e) => last_err = Some(e.into()),
        }
        if attempt < s.upload_http_retries {
            tokio::time::sleep(std::time::Duration::from_secs(1 << attempt)).await;
        }
    }
    Err(last_err.unwrap_or_else(|| anyhow!("upload failed")))
}

fn resolve_knowledge_import_path(api_url: &str) -> &'static str {
    if api_url.contains(":3000") || api_url.contains("127.0.0.1") || api_url.contains("localhost")
    {
        "/knowledge/import-vectors"
    } else {
        "/api/knowledge/import-vectors"
    }
}

fn urlencoding_group(org: &str) -> String {
    org.replace(' ', "%20")
}

fn dir_size(path: &Path) -> Result<u64> {
    let mut total = 0u64;
    for entry in walkdir::WalkDir::new(path) {
        let entry = entry?;
        if entry.file_type().is_file() {
            total += entry.metadata()?.len();
        }
    }
    Ok(total)
}

fn read_jsonl_gz(path: &Path) -> Result<Vec<Value>> {
    use flate2::read::GzDecoder;
    use std::io::{BufRead, BufReader};
    let file = File::open(path)?;
    let decoder = GzDecoder::new(file);
    let reader = BufReader::new(decoder);
    let mut out = Vec::new();
    for line in reader.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        out.push(serde_json::from_str(&line)?);
    }
    Ok(out)
}

pub fn ensure_output_subdir(name: &str) -> PathBuf {
    let dir = settings().work_dir().join(name);
    let _ = fs::create_dir_all(&dir);
    dir
}
