# userbank-local (Rust)

Laptop-only knowledge ingest console for UserBank.

Orchestrates **parse → embed (via userbank-rag) → upload (import-vectors)**. Does not load embedding models (saves RAM).

## Quick start

```bash
cp .env.example .env
# Start rag first (sibling repo):
#   cd ../userbank-rag && make rag-up && cargo run -p userbank-rag

cargo run -p ub-local -- serve
# web (optional)
cd web && npm install && npm run dev   # http://127.0.0.1:5174
```

## CLI

```bash
cargo run -p ub-local -- parse ./doc.md --out ./output/parse
cargo run -p ub-local -- export --corpus ./output/parse/doc_corpus.json --output-dir ./output/bundle --document-id doc
cargo run -p ub-local -- upload --bundle-dir ./output/bundle --mode http
```

## Notes

- Frontend in `web/` unchanged; talks to Rust API on `:8780`.
- Requires running `userbank-rag` for embeddings.
