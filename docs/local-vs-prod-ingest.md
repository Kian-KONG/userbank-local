# Local vs production ingest

| | Local (`userbank-local`) | Production |
|--|--------------------------|------------|
| Repos | + MinerU + DeepRead | api + web + **rag** (runtime) |
| PDF quality OCR | MinerU → DeepRead corpus | No GPU tools |
| Online upload | n/a (this UI is localhost) | Text + PDF → Qwen vision via api→rag |
| Embed / retrieve | Laptop calls local rag `/embeddings` for bundles | Always-on rag for retrieve/index/vision |
| Push to prod | HTTP `/knowledge/import-vectors` or SSH rsync | api + staging import |

```
PDF/Office → MinerU → DeepRead (*_corpus.json)
  → export (RAG embed on laptop)
  → upload (HTTP or rsync) → userbank-api → rag /index → Qdrant
```

**Keep `userbank-rag`.** It is the production retrieval service; this repo only orchestrates laptop ingest.

Env: copy `.env.example`. Never put MinerU/DeepRead into `prep-single-host` / `deploy-single-host`.
