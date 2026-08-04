use serde_json::{json, Value};

#[derive(Debug, Clone)]
pub struct FlatChunk {
    pub id: String,
    pub text: String,
    pub metadata: Value,
}

pub fn flatten_corpus(corpus: &Value, document_id: &str) -> Vec<FlatChunk> {
    let mut points = Vec::new();
    let Some(nodes) = corpus.get("nodes").and_then(|v| v.as_array()) else {
        return points;
    };
    for node in nodes {
        let section_id = node.get("id").and_then(|v| v.as_str()).unwrap_or("");
        let section_title = node.get("title").and_then(|v| v.as_str()).unwrap_or("");
        let paragraphs = node
            .get("paragraphs")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        for (p_idx, paragraph) in paragraphs.iter().enumerate() {
            let text = paragraph_text(paragraph);
            if text.is_empty() {
                continue;
            }
            points.push(FlatChunk {
                id: format!("{document_id}:{section_id}:{p_idx}"),
                text,
                metadata: json!({
                    "section_id": section_id,
                    "section_title": section_title,
                    "paragraph_index": p_idx,
                    "chunk_type": "corpus_paragraph",
                }),
            });
        }
    }
    points
}

fn paragraph_text(paragraph: &Value) -> String {
    if let Some(s) = paragraph.as_str() {
        return s.trim().to_string();
    }
    if let Some(obj) = paragraph.as_object() {
        return obj
            .get("content")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
    }
    String::new()
}
