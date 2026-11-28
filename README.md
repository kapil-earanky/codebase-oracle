# AST-Aware Codebase Oracle

An AST-aware code search and Retrieval-Augmented Generation (RAG) engine built for large source code repositories. Instead of naive fixed-character splitting, it parses source code into Abstract Syntax Trees (ASTs) using Tree-sitter, pairs dense vector embeddings (`pgvector`) with sparse lexical search (`tsvector`) via Reciprocal Rank Fusion (RRF), refines results with a local cross-encoder reranker, and optimizes latency and token costs via a two-tier semantic and provider-prefix caching pipeline.

* **Engineering Spec & SLAs:** [`docs/SPEC.md`](docs/SPEC.md)
* **Architecture Decision Records:** [`docs/adr/README.md`](docs/adr/README.md)

## Architecture Overview

1. **Configuration & Storage (`app/config.py`, `app/db/`, `postgres/schema.sql`):** Typed Pydantic v2 settings, async `psycopg` v3 connection pooling with `pgvector` (`vector(768)` HNSW cosine index for `BAAI/bge-base-en-v1.5`), GIN `tsvector` index, and `repo_sync_state`.
2. **Incremental AST Ingestion (`app/ingestion/`):** Walks local Git repositories via async `git ls-tree` / `git diff --name-status -z` / `git show` (zero GitHub API dependency), parses Python source files with Tree-sitter preserving docstrings and parent scope headers, recursively splits oversized AST nodes, and upserts embeddings + `search_vector` into PostgreSQL.
3. **Hybrid Retrieval & Reranking (`app/retrieval/`, planned):** Runs parallel HNSW dense vector search and GIN full-text search scoped by `(repo_id, commit_sha)`, merges top-50 sets into 25 candidates via RRF ($k=60$), and re-scores with a local cross-encoder (`ms-marco-MiniLM-L-6-v2`) to select the top 5 chunks.
4. **Two-Tier Caching (`app/cache/`, planned):**
   * **Tier 1 (Semantic Cache):** Redis 8 vector similarity ($\ge 0.95$ cosine similarity) scoped to `commit_sha` for `< 20 ms` p95 hits.
   * **Tier 2 (Provider Prompt Prefix Cache):** Separates static system instructions and repository tree maps from dynamic retrieved chunks to maximize provider-side KV prefix caching.
5. **Grounded Streaming API (`app/main.py`, `app/api/`):** FastAPI SSE streaming endpoint enforcing `path/to/file.ext:Lstart-Lend` citations and context-only abstention.
6. **Observability & Evaluation (`app/telemetry/`, `eval/`, planned):** OpenTelemetry spans/metrics exported to Jaeger & Prometheus, plus a CLI evaluation harness computing `Recall@5`, `MRR`, and LLM-as-a-judge faithfulness.

## Prerequisites & Local Setup

* **OS / Hardware:** macOS (Apple Silicon recommended) or Linux
* **Python:** `3.12` (pinned in `.python-version`) managed with [`uv`](https://docs.astral.sh/uv/)
* **Containers:** Docker & Docker Compose

### 1. Start Backing Infrastructure
Spin up PostgreSQL 17 (`pgvector`), Redis 8 (with RediSearch & Vector Sets), Jaeger, and the OpenTelemetry Collector *(Prometheus will be added in Milestone 3)*:

```bash
docker compose up -d
```

### 2. Install Python Dependencies
```bash
uv sync
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env` (defaults match `compose.yml`):

```bash
cp .env.example .env
```

### 4. Run the API Server & Verify Readiness
Run FastAPI natively on your host machine to preserve Apple Silicon Metal/MPS acceleration for local embeddings and reranking:

```bash
uv run uvicorn app.main:app --reload
```

Verify PostgreSQL, `pgvector`, and the `code_chunks` table are ready:

```bash
curl -i http://localhost:8000/health/ready
```

## Development & Quality Checks

```bash
uv run pytest -v        # Run unit test suite
uv run ruff check .     # Lint & import checks
uv run mypy app tests   # Strict type checking
```

## Development Roadmap

* [x] **Milestone 1A:** Project scaffold & PostgreSQL `pgvector` Docker setup
* [ ] **Milestone 1B (In Progress):**
  * [x] Redis 8 + Jaeger + OTel Collector stack & `code_chunks` / `repo_sync_state` schema
  * [x] Typed Pydantic v2 settings, async `psycopg` v3 + `pgvector` pool, and `/health/ready`
  * [x] Local async Git walker & incremental delta calculator (`FR-1`)
  * [ ] Tree-sitter Python AST chunker, context enricher & recursive splitter (`FR-2`)
  * [ ] Batch `BAAI/bge-base-en-v1.5` embedder, idempotent upsert & ingestion benchmark (`NFR-2.1`, `NFR-2.2`)
* [ ] **Milestone 2:** Parallel hybrid retrieval (RRF), cross-encoder reranker & FastAPI SSE citation endpoint
* [ ] **Milestone 3:** Tier-1 Redis semantic cache, Tier-2 provider prefix caching & OTel/Prometheus instrumentation
* [ ] **Milestone 4:** Golden dataset curation, CLI evaluation harness (`Recall@5`, `MRR`) & ablation benchmarks
