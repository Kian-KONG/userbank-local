use crate::config::{path_exists, settings};
use anyhow::{anyhow, Result};
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

pub fn check_mineru() -> Value {
    let p = settings().mineru_path();
    json!({ "ok": path_exists(&p), "path": p.display().to_string() })
}

pub fn check_deepread() -> Value {
    let p = settings().deepread_path();
    json!({ "ok": path_exists(&p), "path": p.display().to_string() })
}

/// Parse document into a corpus JSON path.
/// If input is already `*_corpus.json`, copy/use it.
/// Otherwise attempt DeepRead/MinerU helpers when present; fall back to markdown/plain wrapper.
pub fn parse_document(input: &Path, work: &Path, skip_mineru: bool) -> Result<PathBuf> {
    fs::create_dir_all(work)?;
    let name = input
        .file_name()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "doc".into());

    if name.ends_with("_corpus.json") || name.ends_with(".corpus.json") {
        let dest = work.join("doc_corpus.json");
        fs::copy(input, &dest)?;
        return Ok(dest);
    }

    if name.ends_with(".md") || name.ends_with(".markdown") || name.ends_with(".txt") {
        let text = fs::read_to_string(input)?;
        let corpus = markdown_to_corpus(&name, &text);
        let dest = work.join("doc_corpus.json");
        fs::write(&dest, serde_json::to_string_pretty(&corpus)? + "\n")?;
        return Ok(dest);
    }

    if name.ends_with(".json") {
        // Assume already a corpus-like JSON.
        let dest = work.join("doc_corpus.json");
        fs::copy(input, &dest)?;
        return Ok(dest);
    }

    // PDF / others: try sibling DeepRead CLI if available.
    let deepread = settings().deepread_path();
    if path_exists(&deepread) && !skip_mineru {
        let out = work.join("deepread_out");
        fs::create_dir_all(&out)?;
        let status = Command::new(settings().mineru_python.as_str())
            .arg("-m")
            .arg("deepread")
            .arg(input)
            .arg("--out")
            .arg(&out)
            .current_dir(&deepread)
            .status();
        if let Ok(st) = status {
            if st.success() {
                if let Some(found) = find_corpus(&out) {
                    let dest = work.join("doc_corpus.json");
                    fs::copy(found, &dest)?;
                    return Ok(dest);
                }
            }
        }
    }

    Err(anyhow!(
        "Cannot parse {}: provide *_corpus.json / markdown, or install DeepRead/MinerU siblings",
        input.display()
    ))
}

fn markdown_to_corpus(filename: &str, text: &str) -> Value {
    let paragraphs: Vec<Value> = text
        .split("\n\n")
        .map(|p| p.trim())
        .filter(|p| !p.is_empty())
        .map(|p| json!({ "content": p }))
        .collect();
    json!({
        "filename": filename,
        "nodes": [{
            "id": "root",
            "title": filename,
            "paragraphs": paragraphs,
        }]
    })
}

fn find_corpus(dir: &Path) -> Option<PathBuf> {
    for entry in walkdir::WalkDir::new(dir).into_iter().flatten() {
        let path = entry.path();
        if path
            .file_name()
            .map(|s| {
                let name = s.to_string_lossy();
                name.contains("corpus") && name.ends_with(".json")
            })
            .unwrap_or(false)
        {
            return Some(path.to_path_buf());
        }
    }
    None
}
