# userbank-local (Python)

Laptop-only knowledge ingest console for UserBank.

Orchestrates **parse → embed (via userbank-rag) → upload (import-vectors)**. Does not load embedding models (saves RAM).

Embed quant is fixed to the same **Q8_0** GGUF as production (`Qwen3-Embedding-0.6B-Q8_0.gguf` on the rag host).

## Quick start

```bash
cp .env.example .env
# Start rag first (sibling repo):
#   cd ../userbank-rag && make rag-up && make rag-run

make install
make serve
# web (optional)
cd web && npm install && npm run dev   # http://127.0.0.1:5174
```

## CLI

```bash
.venv/bin/python -m src.main parse ./doc.md --out ./output/parse
.venv/bin/python -m src.main export --corpus ./output/parse/doc_corpus.json --output-dir ./output/bundle --document-id doc
.venv/bin/python -m src.main upload --bundle-dir ./output/bundle --mode http
```

## Notes

- Frontend in `web/` talks to the FastAPI control plane on `:8780`.
- Requires running `userbank-rag` for embeddings (Python + llama.cpp GGUF).
