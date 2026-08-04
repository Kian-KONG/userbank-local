use crate::config::settings;
use anyhow::{anyhow, Context, Result};
use serde_json::json;

pub async fn rag_embed(texts: &[String], input_type: &str) -> Result<Vec<Vec<f32>>> {
    if texts.is_empty() {
        return Ok(Vec::new());
    }
    let s = settings();
    let url = format!("{}/api/v1/embeddings", s.rag_service_url.trim_end_matches('/'));
    let mut req = reqwest::Client::new()
        .post(&url)
        .json(&json!({
            "texts": texts,
            "model": s.embedding_model,
            "input_type": input_type,
        }))
        .timeout(std::time::Duration::from_secs(300));
    if !s.rag_internal_secret.trim().is_empty() {
        req = req.header("X-RAG-Secret", s.rag_internal_secret.trim());
    }
    let resp = req.send().await.context("rag embed request")?;
    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        return Err(anyhow!("RAG embed HTTP {status}: {body}"));
    }
    let data: serde_json::Value = resp.json().await.context("rag embed json")?;
    let embeddings = data["embeddings"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    if embeddings.len() != texts.len() {
        return Err(anyhow!(
            "RAG embed returned {}/{} vectors",
            embeddings.len(),
            texts.len()
        ));
    }
    let mut out = Vec::with_capacity(embeddings.len());
    for v in embeddings {
        let row: Vec<f32> = serde_json::from_value(v).context("vector decode")?;
        if row.len() != s.vector_store_dimension {
            return Err(anyhow!(
                "RAG embed dim {} != {}",
                row.len(),
                s.vector_store_dimension
            ));
        }
        out.push(row);
    }
    Ok(out)
}

pub async fn rag_ready() -> serde_json::Value {
    let s = settings();
    let url = format!("{}/health/ready", s.rag_service_url.trim_end_matches('/'));
    match reqwest::Client::new()
        .get(&url)
        .timeout(std::time::Duration::from_secs(5))
        .send()
        .await
    {
        Ok(resp) => json!({
            "ok": resp.status().is_success(),
            "status": resp.status().as_u16(),
            "body": resp.text().await.unwrap_or_default().chars().take(500).collect::<String>(),
        }),
        Err(e) => json!({ "ok": false, "error": e.to_string() }),
    }
}
