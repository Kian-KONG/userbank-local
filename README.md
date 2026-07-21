# userbank-local

Laptop-only knowledge ingest for UserBank (M4 Mac Mini / GPU workstation).

**Not deployed to production.** This repo orchestrates **MinerU → DeepRead → local RAG embed → HTTP/rsync upload**.

## Repo roles (do not merge these)

| Repo | Role | Deploy online? |
|------|------|----------------|
| **userbank-rag** | Runtime sidecar: embed / retrieve / index / vision / rerank → Qdrant | **Yes** (always on) |
| **userbank-api** | Business API, PG/OSS, calls rag, receives import-vectors | **Yes** |
| **userbank-web** | Product UI (PDF + text upload → Qwen vision via api) | **Yes** |
| **userbank-local** (this) | Local GPU ingest console + sync to prod | **No** |
| MinerU / DeepRead | Local parse tooling (siblings) | **No** |

`userbank-local` **does not replace** `userbank-rag`. Online chat/search still goes `web → api → rag → Qdrant`. Local only uses rag’s `/embeddings` on the laptop when building bundles.

## Quick start

```bash
cd userbank-local
cp .env.example .env   # set SURVEY_IMPORT_SECRET, RAG_SERVICE_URL, etc.
make install           # Python ≥3.11 (prefer 3.12) + web npm
make up
# web  http://127.0.0.1:5174
# api  http://127.0.0.1:8780/health
make down
```

Sibling layout expected:

```text
UserBank/
  userbank-local/   # this repo
  userbank-api/
  userbank-rag/
  userbank-web/
  MinerU/
  DeepRead/
```

## CLI

```bash
uv run ub-local serve
uv run ub-local parse ./doc.pdf --out ./output/parse
uv run ub-local export --corpus ./doc_corpus.json --output-dir ./output/bundle --document-id doc
uv run ub-local upload --bundle-dir ./output/bundle --mode auto
```

## Docs

See [docs/local-vs-prod-ingest.md](docs/local-vs-prod-ingest.md).
