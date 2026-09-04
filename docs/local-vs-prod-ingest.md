# Local vs production ingest

| | Local (`userbank-local`) | Production |
|--|--------------------------|------------|
| Repos | + MinerU + LibreOffice + **rag** (embed/vision) | api + web + **rag** (runtime) |
| PDF / Word | Report PDF + DOCX→PDF → MinerU. Slide-shaped PDF → same vision path as PPT | Text + PDF → Qwen vision (runtime) |
| PPT / PPTM | LibreOffice → PNG → rag `describe-pages` (`qwen3.8-max`) | — |
| Excel | Workbook IR → sheet classify → chunks | — |
| Embed | **Always on laptop** via local rag `/embeddings` | Import does **not** re-embed |
| Progress | UI job `phase` + `progress` % + logs | — |
| Push to prod | HTTP or SSH rsync pre-embedded bundle | api staging / import-vectors |

```
PDF (report / A4) / DOCX:  (Word → PDF) → MinerU → corpus → embed → upload
PDF (slides) / PPT*:       LibreOffice if needed → PNG → qwen3.8-max → corpus → embed → upload
Excel:                     IR + classify → chunks → embed → upload
Markdown:                  local corpus → embed → upload
```

Routing is by suffix first (Excel is always table IR; PPT* is always vision). `.pdf` is then split by type: PowerPoint/Impress producer or widescreen page size → Qwen; A4/Letter reports → MinerU. The UI knowledge/survey toggle does not pick a parser.

Progress: React polls `GET /jobs/:id` (`phase`: parse|vision|embed|upload, `progress` 0–100).

Env: copy `.env.example`. PPT needs LibreOffice (`soffice`) + local `pypdfium2` (via `make install`) + running `userbank-rag` vision. PDF/DOCX need sibling `../MinerU`. Embed always uses rag. Control plane is Python FastAPI (`make serve`); UI remains React in `web/`.
