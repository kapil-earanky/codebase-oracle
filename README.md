# AST-Aware Codebase Oracle

An AST-aware code search and Retrieval-Augmented Generation (RAG) engine built for large source code repositories. Instead of naive fixed-character splitting, it parses source code into Abstract Syntax Trees (ASTs) using Tree-sitter, pairs dense vector embeddings (`pgvector`) with sparse lexical search (`BM25`/`tsvector`) via Reciprocal Rank Fusion (RRF), refines results with a local cross-encoder reranker, and optimizes latency and token costs via a two-tier semantic and provider-prefix caching pipeline.

Full architectural requirements and SLAs are documented in [`docs/SPEC.md`](docs/SPEC.md).

## Architecture Overview

1. **Incremental AST Ingestion (`ingestion/`):** Walks local Git working trees via `git diff` / `git ls-tree`, parses Python source files with Tree-sitter, preserves leading docstrings/comments and parent scope headers, recursively splits oversized AST nodes, and upserts embeddings + `tsvector` indexes into PostgreSQL.
2. **Hybrid Retrieval & Reranking (`retrieval/`):** Runs parallel HNSW dense vector search and GIN full-text search scoped by `repo_id` and `commit_sha`, merges the top-50 sets into 25 candidates via RRF ($k=60$), and re-scores them with a local cross-encoder (`ms-marco-MiniLM-L-6-v2`) to select the top 5 chunks.
3. **Two-Tier Caching (`cache/`):**
   * **Tier 1 (Semantic Cache):** Checks Redis vector similarity ($\ge 0.95$ cosine similarity) scoped to the target commit SHA for sub-20ms cache hits.
   * **Tier 2 (Provider Prompt Prefix Cache):** Separates static system instructions and repository tree maps from dynamic retrieved chunks to maximize provider-side KV prefix cache hits.
4. **Grounded Streaming API (`api/`):** FastAPI SSE streaming endpoint enforcing `path/to/file.ext:Lstart-Lend` citations and strict context-only abstention.
5. **Observability & Evaluation (`telemetry/`, `eval/`):** OpenTelemetry tracing exported to Jaeger/Prometheus, plus a CLI evaluation harness measuring `Recall@5`, `MRR`, and LLM-as-a-judge faithfulness.

## Prerequisites & Local Setup

* **OS / Hardware:** macOS (Apple Silicon recommended) or Linux
* **Python:** 3.11+ managed with [`uv`](https://docs.astral.sh/uv/)
* **Containers:** Docker & Docker Compose

### 1. Start Backing Infrastructure
Spin up PostgreSQL (`pgvector`), Redis, and the OpenTelemetry/Jaeger/Prometheus stack:

```bash
docker compose up -d
```

### 2. Install Python Dependencies
```bash
uv sync
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env` and populate your API keys and database DSNs:

```bash
cp .env.example .env
```

### 4. Run the API Server
Run FastAPI natively on your host machine (recommended on Apple Silicon to utilize Metal/MPS acceleration for local reranker inference):

```bash
uv run uvicorn app.main:app --reload
```

## Development Roadmap

* [x] **Milestone 1A:** Project scaffold & PostgreSQL `pgvector` Docker setup
* [ ] **Milestone 1B:** Redis + OTel/Jaeger stack, `code_chunks` schema, Git delta walker & Tree-sitter AST chunker
* [ ] **Milestone 2:** Parallel hybrid retrieval (RRF), cross-encoder reranker & FastAPI SSE citation endpoint
* [ ] **Milestone 3:** Tier-1 Redis semantic cache, Tier-2 provider prefix caching & OTel instrumentation
* [ ] **Milestone 4:** Golden dataset curation, CLI evaluation harness (`Recall@5`, `MRR`) & ablation benchmarks