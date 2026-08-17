# Local vs production ingest

| | Local (`userbank-local`) | Production |
|--|--------------------------|------------|
| Repos | + MinerU + DeepRead | api + web + **rag** (runtime) |
| Knowledge track | PDF / papers → MinerU → DeepRead | Text + PDF → Qwen vision |
| Image / PPT track | PDF / PPTX → Plus per page → Max outline | — |
| Survey track | Excel / Word / `chunks.jsonl.gz` | `/survey/import-vectors` |
| Embed | **Always on laptop** via local rag `/embeddings` | Import does **not** re-embed |
| Progress | UI job `phase` + `progress` % + logs; `make logs` | — |
| Push to prod | HTTP or SSH rsync pre-embedded bundle | api staging / import-vectors |

```
Knowledge: PDF → MinerU → DeepRead → embed (laptop) → upload
Image/PPT: PDF/PPTX → page PNG → Plus (1 image) → Max outline → embed → upload
Survey:    xlsx/docx/jsonl → chunks → embed (laptop) → upload
```

Progress: React polls `GET /jobs/:id` (`phase`: parse|embed|upload, `progress` 0–100).

Env: copy `.env.example`. Never put MinerU/DeepRead into `prep-single-host` / `deploy-single-host`. Control plane is Python FastAPI (`make serve`); UI remains React in `web/`.
